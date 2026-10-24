#!/usr/bin/env python3
"""One command after git pull: deps, venv, audio, server, open URLs.

Typical use (from the repo root):

    ./run
    python3 runner.py
    python3 runner.py --stop
    python3 runner.py --foreground
    python3 runner.py --force-audio
    python3 runner.py --lan

Creates/uses ``.venv``, installs requirements when they change, downloads
models if missing, regenerates listen clips when needed, restarts the server,
and prints URLs. Default bind is localhost; pass ``--lan`` for Wi‑Fi devices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

# Files that change listen-clip generation / postprocess / content inventory.
AUDIO_INPUT_PATHS: tuple[str, ...] = (
    "app/audio_files.py",
    "app/config.py",
    "scripts/generate_audio.py",
    "content/items.json",
)

STAMP_PATH = config.DATA_DIR / "runner_audio_stamp.json"
DEPS_STAMP_PATH = config.DATA_DIR / "runner_deps_stamp.json"
PID_PATH = config.DATA_DIR / "runner_uvicorn.pid"
LOG_DIR = config.DATA_DIR / "logs"
LAUNCHD_LABEL = "com.readingbuddy.server"
REQUIREMENTS = ROOT / "requirements.txt"
# Intersection of upstream requires-python / wheels:
#   kokoro-onnx: >=3.10,<3.14
#   onnxruntime / ctranslate2: solid wheels for 3.11–3.13 (not 3.15)
MIN_PY = (3, 11)
MAX_PY = (3, 13)
# Prefer a known-good CPython for Windows/macOS installs.
PREFERRED_PY = ((3, 12), (3, 11), (3, 13))

# Import smoke-test after pip install (names, not versions).
RUNTIME_IMPORTS = (
    "fastapi",
    "uvicorn",
    "faster_whisper",
    "ctranslate2",
    "kokoro_onnx",
    "onnxruntime",
    "metaphone",
    "soundfile",
    "numpy",
    "httpx",
    "pydantic",
)


def _venv_dir() -> Path:
    return ROOT / ".venv"


def _venv_python() -> Path:
    if platform.system() == "Windows":
        return _venv_dir() / "Scripts" / "python.exe"
    return _venv_dir() / "bin" / "python"


def _using_project_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == _venv_python().resolve()
    except OSError:
        return False


def _parse_version_text(text: str) -> tuple[int, int] | None:
    text = (text or "").strip()
    try:
        major_s, minor_s = text.split(".", 1)
        return int(major_s), int(minor_s.split(".", 1)[0])
    except ValueError:
        return None


def _python_version(cmd: list[str]) -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            [*cmd, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return _parse_version_text(out.stdout or "")


def _version_supported(version: tuple[int, int]) -> bool:
    return MIN_PY <= version <= MAX_PY


def _python_install_hint() -> str:
    band = f"{MIN_PY[0]}.{MIN_PY[1]}–{MAX_PY[0]}.{MAX_PY[1]}"
    if platform.system() == "Windows":
        return (
            f"Need Python {band} (3.12 recommended). "
            "Python 3.14/3.15 cannot install faster-whisper/ctranslate2 yet.\n"
            "  winget install Python.Python.3.12\n"
            "  Remove-Item -Recurse -Force .venv\n"
            "  py -3.12 runner.py\n"
            "Also install: winget install --id eSpeak-NG.eSpeak-NG -e"
        )
    if platform.system() == "Darwin":
        return (
            f"Need Python {band} (3.12 recommended).\n"
            "  brew install python@3.12\n"
            "  rm -rf .venv && ./run"
        )
    return f"Install Python 3.12 ({band}), delete .venv, and re-run."


def verify_runtime_imports(py: str | None = None) -> None:
    """Fail fast if a required package did not install into the venv."""
    exe = py or str(_venv_python())
    code = "import " + ", ".join(RUNTIME_IMPORTS)
    try:
        subprocess.run(
            [exe, "-c", code],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Venv python not found: {exe}\n" + _python_install_hint()
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            "Dependency import check failed after pip install.\n"
            f"{detail}\n" + _python_install_hint()
        ) from exc


def find_system_python() -> Path:
    """Pick a supported CPython (3.11–3.13), preferring 3.12."""
    commands: list[list[str]] = []
    for name in (
        "python3.12",
        "python3.11",
        "python3.13",
        "python3",
        "python",
    ):
        found = shutil.which(name)
        if found:
            commands.append([found])
    if platform.system() == "Windows" and shutil.which("py"):
        for flag in ("-3.12", "-3.11", "-3.13"):
            commands.append(["py", flag])
    # Current interpreter last — may be too new (e.g. pythoncore-3.15).
    commands.append([sys.executable])

    found_versions: list[tuple[tuple[int, int], Path]] = []
    seen: set[str] = set()
    for cmd in commands:
        version = _python_version(cmd)
        if version is None or not _version_supported(version):
            continue
        # Resolve to a real executable path for venv creation.
        try:
            out = subprocess.run(
                [*cmd, "-c", "import sys; print(sys.executable)"],
                check=True,
                capture_output=True,
                text=True,
            )
            exe = Path((out.stdout or "").strip())
            key = str(exe.resolve()) if exe.is_file() else str(cmd)
        except (OSError, subprocess.CalledProcessError):
            continue
        if key in seen or not exe.is_file():
            continue
        seen.add(key)
        found_versions.append((version, exe))

    if not found_versions:
        raise RuntimeError(
            f"Need Python {MIN_PY[0]}.{MIN_PY[1]}–{MAX_PY[0]}.{MAX_PY[1]} "
            f"(3.12 recommended). faster-whisper does not install on newer Pythons yet.\n"
            + _python_install_hint()
        )

    def sort_key(item: tuple[tuple[int, int], Path]) -> tuple[int, tuple[int, int]]:
        version, _path = item
        try:
            rank = PREFERRED_PY.index(version)
        except ValueError:
            rank = len(PREFERRED_PY)
        return (rank, version)

    found_versions.sort(key=sort_key)
    return found_versions[0][1]


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        check=check,
        text=True,
        env=env,
    )


def ensure_venv() -> Path:
    """Create ``.venv`` if needed; recreate when it uses an unsupported Python."""
    py = _venv_python()
    if py.is_file():
        version = _python_version([str(py)])
        if version is not None and _version_supported(version):
            return py
        label = f"{version[0]}.{version[1]}" if version else "unknown"
        print(
            f"Existing .venv uses Python {label}; "
            f"need {MIN_PY[0]}.{MIN_PY[1]}–{MAX_PY[0]}.{MAX_PY[1]}. Recreating…",
            flush=True,
        )
        shutil.rmtree(_venv_dir(), ignore_errors=True)

    system = find_system_python()
    version = _python_version([str(system)])
    label = f"{version[0]}.{version[1]}" if version else "?"
    print(f"Creating virtualenv with Python {label}: {system} …", flush=True)
    _run([str(system), "-m", "venv", str(_venv_dir())])
    if not py.is_file():
        raise RuntimeError(f"venv python missing after create: {py}")
    return py


def reexec_in_venv_if_needed(argv: list[str]) -> None:
    """Re-launch this script under ``.venv`` so imports use project deps."""
    if _using_project_venv():
        return
    venv_py = ensure_venv()
    print(f"Using venv: {venv_py}", flush=True)
    os.execv(str(venv_py), [str(venv_py), str(ROOT / "runner.py"), *argv])


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json_stamp(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def ensure_deps(*, force: bool = False) -> bool:
    """pip install -r requirements.txt when the lockfile changed or imports fail.

    Returns True when pip install ran.
    """
    if not REQUIREMENTS.is_file():
        raise RuntimeError(f"Missing {REQUIREMENTS}")

    req_hash = file_digest(REQUIREMENTS)
    stamp = _load_json_stamp(DEPS_STAMP_PATH) or {}
    imports_ok = True
    try:
        verify_runtime_imports(str(_venv_python()))
    except RuntimeError:
        imports_ok = False

    if not force and stamp.get("requirements_sha256") == req_hash and imports_ok:
        print("Dependencies up to date — skip pip install.", flush=True)
        return False

    reason = "forced" if force else ("imports missing" if not imports_ok else "requirements.txt changed")
    print(f"Installing Python packages ({reason})…", flush=True)
    py = str(_venv_python())
    venv_ver = _python_version([py])
    if venv_ver is not None and not _version_supported(venv_ver):
        raise RuntimeError(
            f".venv is Python {venv_ver[0]}.{venv_ver[1]}; "
            f"need {MIN_PY[0]}.{MIN_PY[1]}–{MAX_PY[0]}.{MAX_PY[1]}.\n"
            + _python_install_hint()
        )
    try:
        _run([py, "-m", "pip", "install", "--upgrade", "pip"])
        _run([py, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "pip install failed. If you see 'no matching distribution' for "
            "ctranslate2 / faster-whisper / onnxruntime, your Python is too new "
            f"(need {MIN_PY[0]}.{MIN_PY[1]}–{MAX_PY[0]}.{MAX_PY[1]}).\n"
            + _python_install_hint()
        ) from exc
    verify_runtime_imports(py)
    # pip check catches broken dependency graphs (optional but useful).
    check = subprocess.run(
        [py, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        print("WARNING: pip check reported issues:", flush=True)
        print((check.stdout or check.stderr or "").strip(), flush=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEPS_STAMP_PATH.write_text(
        json.dumps(
            {
                "requirements_sha256": req_hash,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "python": f"{venv_ver[0]}.{venv_ver[1]}" if venv_ver else None,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return True


def kokoro_ready() -> bool:
    return (
        config.KOKORO_MODEL_PATH.is_file()
        and config.KOKORO_VOICES_PATH.is_file()
        and config.KOKORO_MODEL_PATH.stat().st_size > 0
        and config.KOKORO_VOICES_PATH.stat().st_size > 0
    )


def whisper_files_ready() -> bool:
    """True when a non-empty Whisper ``model.bin`` exists under ``models/``.

    Empty dirs / partial downloads (config only) do not count as ready.
    """
    local = config.MODELS_DIR / "whisper-small.en"
    if local.is_dir():
        for bin_path in local.rglob("model.bin"):
            if bin_path.is_file() and bin_path.stat().st_size > 0:
                return True
    # faster-whisper / HF hub layout under download_root
    for path in config.MODELS_DIR.glob("models--*whisper*"):
        if not path.is_dir():
            continue
        for bin_path in path.rglob("model.bin"):
            if bin_path.is_file() and bin_path.stat().st_size > 0:
                return True
    for path in config.MODELS_DIR.glob("**/faster-whisper-small.en/**/model.bin"):
        if path.is_file() and path.stat().st_size > 0:
            return True
    return False


def models_ready() -> bool:
    """Kokoro listen clips + Whisper ASR weights both present (non-empty)."""
    return kokoro_ready() and whisper_files_ready()


def ensure_models() -> bool:
    """Download Whisper + Kokoro once when model files are missing."""
    if models_ready():
        print("Models present — skip download.", flush=True)
        return False
    missing = []
    if not kokoro_ready():
        missing.append("Kokoro")
    if not whisper_files_ready():
        missing.append("Whisper")
    print(
        f"Downloading models ({', '.join(missing) or 'Whisper + Kokoro'}) — needs network once…",
        flush=True,
    )
    _run([str(_venv_python()), str(ROOT / "scripts" / "download_models.py")])
    if not models_ready():
        parts = []
        if not kokoro_ready():
            parts.append(f"Kokoro at {config.KOKORO_MODEL_PATH}")
        if not whisper_files_ready():
            parts.append(f"Whisper under {config.MODELS_DIR}")
        raise RuntimeError(
            "Model download finished but files are still missing. "
            "Run ./run again after checking the network. Expected: "
            + "; ".join(parts)
        )
    return True


def ensure_system_tools() -> None:
    missing: list[str] = []
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if not (shutil.which("espeak") or shutil.which("espeak-ng")):
        missing.append("espeak or espeak-ng")
    if missing:
        tip = {
            "Darwin": "brew install ffmpeg espeak",
            "Windows": "winget install Gyan.FFmpeg and eSpeak-NG.eSpeak-NG",
            "Linux": "sudo apt install ffmpeg espeak-ng",
        }.get(platform.system(), "install ffmpeg and espeak-ng")
        print(
            "WARNING: missing tools: "
            + ", ".join(missing)
            + f"\n  Install with: {tip}",
            flush=True,
        )


def audio_inputs_fingerprint() -> dict[str, str]:
    """Map relative audio-input paths → sha256 (missing files → empty)."""
    out: dict[str, str] = {}
    for rel in AUDIO_INPUT_PATHS:
        path = ROOT / rel
        out[rel] = file_digest(path) if path.is_file() else ""
    return out


def load_stamp() -> dict[str, str] | None:
    payload = _load_json_stamp(STAMP_PATH)
    if not payload:
        return None
    files = payload.get("files")
    return files if isinstance(files, dict) else None


def save_stamp(files: dict[str, str]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    STAMP_PATH.write_text(
        json.dumps(
            {"files": files, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def content_slugs() -> list[str]:
    items_path = config.CONTENT_ITEMS
    if not items_path.is_file():
        return []
    payload = json.loads(items_path.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("items", [])
    return [str(item["slug"]) for item in items if item.get("slug")]


def audio_ready() -> bool:
    from app.audio_files import generated_audio_ready

    slugs = content_slugs()
    if not slugs:
        return False
    return generated_audio_ready(slugs)


def maybe_regenerate_audio(*, force: bool = False) -> bool:
    """Regenerate clips when inputs changed, stamp missing, or audio incomplete.

    Returns True when generate_audio.py was invoked.
    """
    current = audio_inputs_fingerprint()
    previous = load_stamp()
    inputs_changed = previous != current
    ready = audio_ready()

    if not force and not inputs_changed and ready:
        print("Audio inputs unchanged and clips ready — skip generate.", flush=True)
        return False

    py = str(_venv_python())
    cmd = [py, str(ROOT / "scripts" / "generate_audio.py")]
    if force or inputs_changed:
        cmd.append("--force")
        reason = "forced" if force else "audio inputs changed"
    else:
        reason = "clips missing or incomplete"
    print(f"Regenerating audio ({reason})…", flush=True)
    _run(cmd)
    save_stamp(current)
    if not audio_ready():
        print(
            "WARNING: audio still not ready after generate_audio.py. "
            "Check Kokoro models / espeak / ffmpeg.",
            flush=True,
        )
    return True


def maybe_regenerate_illustrations() -> bool:
    keys = ROOT / "static" / "illustrations" / "keys.json"
    if keys.is_file():
        return False
    script = ROOT / "scripts" / "generate_illustrations.py"
    if not script.is_file():
        return False
    print("Illustrations missing — generating…", flush=True)
    _run([str(_venv_python()), str(script)])
    return True


def health_url() -> str:
    return f"http://127.0.0.1:{config.PORT}/api/health"


def health_ok(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(health_url(), timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("whisper") and body.get("ffmpeg"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def lan_ips() -> list[str]:
    """Best-effort IPv4 addresses useful on the same Wi‑Fi."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def resolve_bind_host(args: argparse.Namespace) -> str:
    """Localhost by default; ``--lan`` opens Wi‑Fi. ``--localhost-only`` is a no-op alias."""
    if bool(getattr(args, "lan", False)):
        return "0.0.0.0"
    return "127.0.0.1"


def print_ready_banner(*, bind_host: str) -> None:
    port = config.PORT
    print("", flush=True)
    print("Reading Buddy is ready", flush=True)
    print(f"  This computer:  http://127.0.0.1:{port}", flush=True)
    print(f"  Parent page:    http://127.0.0.1:{port}/parent", flush=True)
    if bind_host in ("0.0.0.0", "::"):
        ips = lan_ips()
        if ips:
            for ip in ips:
                print(f"  Same Wi‑Fi:     http://{ip}:{port}", flush=True)
        else:
            print("  Same Wi‑Fi:     (could not detect LAN IP)", flush=True)
    else:
        print("  (localhost only — pass ./run --lan for phone/tablet on Wi‑Fi)", flush=True)
    print(f"  Health:         {health_url()}", flush=True)
    print("  Stop later:     ./run --stop", flush=True)
    print("", flush=True)


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_plist_body(python: Path, *, bind_host: str) -> str:
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / "uvicorn.out.log"
    stderr = log_dir / "uvicorn.err.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCHD_LABEL}</string>
  <key>WorkingDirectory</key>
  <string>{ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>{bind_host}</string>
    <string>--port</string>
    <string>{config.PORT}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HF_HUB_OFFLINE</key>
    <string>1</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{stdout}</string>
  <key>StandardErrorPath</key>
  <string>{stderr}</string>
</dict>
</plist>
"""


def launchctl_available() -> bool:
    return platform.system() == "Darwin" and shutil.which("launchctl") is not None


def stop_launchd() -> None:
    if not launchctl_available():
        return
    plist = launchd_plist_path()
    uid = os.getuid()
    target = f"gui/{uid}/{LAUNCHD_LABEL}"
    subprocess.run(
        ["launchctl", "bootout", target],
        check=False,
        capture_output=True,
        text=True,
    )
    if plist.is_file():
        subprocess.run(
            ["launchctl", "unload", str(plist)],
            check=False,
            capture_output=True,
            text=True,
        )
        print(f"Stopped LaunchAgent {LAUNCHD_LABEL}", flush=True)


def start_launchd(*, bind_host: str) -> None:
    if not launchctl_available():
        raise RuntimeError("launchctl is only available on macOS")
    python = _venv_python()
    plist = launchd_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    stop_launchd()
    plist.write_text(launchd_plist_body(python, bind_host=bind_host), encoding="utf-8")
    uid = os.getuid()
    domain = f"gui/{uid}"
    boot = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist)],
        check=False,
        capture_output=True,
        text=True,
    )
    if boot.returncode != 0:
        _run(["launchctl", "load", "-w", str(plist)], check=False)
    else:
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"{domain}/{LAUNCHD_LABEL}"],
            check=False,
            capture_output=True,
            text=True,
        )
    print(f"LaunchAgent loaded: {plist}", flush=True)
    print(f"Logs: {LOG_DIR / 'uvicorn.out.log'}", flush=True)


def stop_pidfile() -> None:
    if not PID_PATH.is_file():
        return
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except ValueError:
        PID_PATH.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped uvicorn pid {pid}", flush=True)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        print(f"Could not stop pid {pid}: {exc}", flush=True)
    PID_PATH.unlink(missing_ok=True)


def _free_port() -> None:
    """Best-effort kill whatever is listening on the app port (macOS/Linux)."""
    if platform.system() == "Windows":
        return
    try:
        out = subprocess.run(
            ["lsof", f"-tiTCP:{config.PORT}", "-sTCP:LISTEN"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return
    for line in (out.stdout or "").split():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Freed port {config.PORT} (stopped pid {pid})", flush=True)
        except (ProcessLookupError, PermissionError):
            pass


def start_uvicorn_background(*, bind_host: str) -> None:
    """Detach uvicorn and record a pidfile (non-macOS service fallback)."""
    stop_pidfile()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = open(LOG_DIR / "uvicorn.out.log", "a", encoding="utf-8")  # noqa: SIM115
    err = open(LOG_DIR / "uvicorn.err.log", "a", encoding="utf-8")  # noqa: SIM115
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [
            str(_venv_python()),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            bind_host,
            "--port",
            str(config.PORT),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=out,
        stderr=err,
        start_new_session=True,
    )
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    print(f"Started uvicorn pid {proc.pid}", flush=True)


def start_uvicorn_foreground(*, bind_host: str) -> None:
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    print(
        f"Starting uvicorn on http://{bind_host}:{config.PORT} (Ctrl+C to stop)",
        flush=True,
    )
    os.execvpe(
        str(_venv_python()),
        [
            str(_venv_python()),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            bind_host,
            "--port",
            str(config.PORT),
        ],
        env,
    )


def wait_for_health(*, seconds: float = 90.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if health_ok():
            print(f"Healthy: {health_url()}", flush=True)
            return True
        time.sleep(0.5)
    print(
        f"WARNING: health check did not pass within {seconds:.0f}s ({health_url()})",
        flush=True,
    )
    return False


def stop_all() -> None:
    stop_launchd()
    stop_pidfile()
    _free_port()
    time.sleep(0.4)
    if health_ok(timeout=0.5):
        print(
            f"Something is still answering on port {config.PORT}. "
            "Stop it manually if needed.",
            flush=True,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bootstrap deps/venv, refresh audio if needed, restart Reading Buddy."
    )
    p.add_argument("--no-audio", action="store_true", help="Skip audio stamp / regenerate")
    p.add_argument(
        "--force-audio",
        action="store_true",
        help="Force regenerate all generated wavs",
    )
    p.add_argument(
        "--force-deps",
        action="store_true",
        help="Force pip install -r requirements.txt",
    )
    p.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip venv/pip/model bootstrap (audio + server only)",
    )
    p.add_argument(
        "--foreground",
        action="store_true",
        help="Run uvicorn in this terminal (default when launchctl is unavailable)",
    )
    p.add_argument(
        "--background",
        action="store_true",
        help="Detach uvicorn with a pidfile (used when not on macOS launchd)",
    )
    p.add_argument(
        "--launchd",
        action="store_true",
        help="Force LaunchAgent install via launchctl (macOS only)",
    )
    p.add_argument("--stop", action="store_true", help="Stop LaunchAgent / background uvicorn")
    p.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for /api/health after start",
    )
    net = p.add_mutually_exclusive_group()
    net.add_argument(
        "--lan",
        action="store_true",
        help="Bind 0.0.0.0 so phones/tablets on Wi‑Fi can connect",
    )
    net.add_argument(
        "--localhost-only",
        action="store_true",
        help="Bind 127.0.0.1 only (default; kept for older scripts)",
    )
    p.add_argument(
        "--backup",
        action="store_true",
        help="Zip data/ progress (DB + settings) and exit",
    )
    p.add_argument(
        "--restore",
        metavar="ZIP",
        default=None,
        help="Restore data/ from a backup zip and exit",
    )
    p.add_argument(
        "--force-restore",
        action="store_true",
        help="Allow --restore to overwrite an existing reading.db",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    args = parse_args(raw)
    os.chdir(ROOT)
    config.ensure_dirs()

    if args.backup:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "backup_data.py"), "backup"],
            cwd=ROOT,
        ).returncode
    if args.restore:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "backup_data.py"),
            "restore",
            str(args.restore),
        ]
        if args.force_restore:
            cmd.append("--force")
        return subprocess.run(cmd, cwd=ROOT).returncode

    if args.stop:
        stop_all()
        return 0

    if not args.skip_deps:
        # Create venv with system Python, then re-exec under it before pip/imports.
        ensure_venv()
        reexec_in_venv_if_needed(raw)
        ensure_system_tools()
        ensure_deps(force=args.force_deps)
        ensure_models()
        maybe_regenerate_illustrations()

    if not args.no_audio:
        maybe_regenerate_audio(force=args.force_audio)

    bind_host = resolve_bind_host(args)

    # Always restart so a git pull + ./run picks up new code.
    print("Restarting server…", flush=True)
    stop_all()

    if args.launchd:
        if not launchctl_available():
            print("ERROR: --launchd requires macOS launchctl.", file=sys.stderr)
            return 2
        mode = "launchd"
    elif args.background:
        mode = "background"
    elif args.foreground:
        mode = "foreground"
    elif launchctl_available():
        mode = "launchd"
    else:
        mode = "foreground"

    if mode == "launchd":
        start_launchd(bind_host=bind_host)
        if not args.no_wait:
            wait_for_health()
        print_ready_banner(bind_host=bind_host)
        return 0

    if mode == "background":
        start_uvicorn_background(bind_host=bind_host)
        if not args.no_wait:
            wait_for_health()
        print_ready_banner(bind_host=bind_host)
        return 0

    # Foreground — print URLs first; process is replaced by uvicorn.
    print_ready_banner(bind_host=bind_host)
    start_uvicorn_foreground(bind_host=bind_host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
