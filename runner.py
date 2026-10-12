#!/usr/bin/env python3
"""Pull updates, regenerate listen clips when audio inputs change, start the app.

Typical use (from the repo root, after one-time setup):

    python runner.py              # pull → maybe regen audio → start
    python runner.py --stop       # stop launchd job or local uvicorn
    python runner.py --foreground # uvicorn in this terminal (any OS)
    python runner.py --no-pull    # skip git pull
    python runner.py --force-audio

On macOS, the default start path installs/loads a LaunchAgent via ``launchctl``
so Reading Buddy comes back after reboot. Elsewhere (or with ``--foreground``),
uvicorn runs in the foreground on 127.0.0.1:8765.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
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
PID_PATH = config.DATA_DIR / "runner_uvicorn.pid"
LOG_DIR = config.DATA_DIR / "logs"
LAUNCHD_LABEL = "com.readingbuddy.server"
HEALTH_URL = f"http://{config.HOST}:{config.PORT}/api/health"


def _venv_python() -> Path:
    if platform.system() == "Windows":
        candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.is_file() else Path(sys.executable)


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


def git_pull(*, remote: str = "origin") -> None:
    """Fetch and fast-forward the current branch when possible."""
    if not (ROOT / ".git").exists():
        print("No .git directory — skipping pull.", flush=True)
        return
    # Keep local WIP safe: only pull if working tree is clean enough for ff.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    dirty = bool(status.stdout.strip())
    if dirty:
        print(
            "Working tree has local changes — skipping git pull "
            "(commit/stash first, or pass --no-pull).",
            flush=True,
        )
        return
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _run(["git", "fetch", remote])
    # Prefer merge --ff-only so we never create surprise merge commits.
    result = subprocess.run(
        ["git", "merge", "--ff-only", f"{remote}/{branch}"],
        cwd=str(ROOT),
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        # Branch may be local-only or already up to date under another name.
        alt = subprocess.run(
            ["git", "pull", "--ff-only", remote, branch],
            cwd=str(ROOT),
            check=False,
            text=True,
            capture_output=True,
        )
        if alt.returncode != 0:
            print(
                "git pull could not fast-forward "
                f"(branch={branch}). Continuing with local tree.\n"
                f"{(result.stderr or alt.stderr or '').strip()}",
                flush=True,
            )
            return
        print((alt.stdout or "").strip() or "Already up to date.", flush=True)
        return
    print((result.stdout or "").strip() or "Already up to date.", flush=True)


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def audio_inputs_fingerprint() -> dict[str, str]:
    """Map relative audio-input paths → sha256 (missing files → empty)."""
    out: dict[str, str] = {}
    for rel in AUDIO_INPUT_PATHS:
        path = ROOT / rel
        out[rel] = file_digest(path) if path.is_file() else ""
    return out


def load_stamp() -> dict[str, str] | None:
    if not STAMP_PATH.is_file():
        return None
    try:
        payload = json.loads(STAMP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    files = payload.get("files")
    return files if isinstance(files, dict) else None


def save_stamp(files: dict[str, str]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    STAMP_PATH.write_text(
        json.dumps({"files": files, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2)
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
        reason = "forced" if force else "audio inputs changed after pull/update"
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


def health_ok(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("whisper") and body.get("ffmpeg"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def launchd_plist_path() -> Path:
    home = Path.home()
    return home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_plist_body(python: Path) -> str:
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / "uvicorn.out.log"
    stderr = log_dir / "uvicorn.err.log"
    # Keep XML simple — paths should not need exotic escaping for this project.
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
    <string>{config.HOST}</string>
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
    # Older macOS / habit: unload by plist path too.
    if plist.is_file():
        subprocess.run(
            ["launchctl", "unload", str(plist)],
            check=False,
            capture_output=True,
            text=True,
        )
        print(f"Stopped LaunchAgent {LAUNCHD_LABEL}", flush=True)


def start_launchd() -> None:
    if not launchctl_available():
        raise RuntimeError("launchctl is only available on macOS")
    python = _venv_python()
    plist = launchd_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    stop_launchd()
    plist.write_text(launchd_plist_body(python), encoding="utf-8")
    uid = os.getuid()
    domain = f"gui/{uid}"
    # bootout may have removed it; bootstrap + kickstart is the modern path.
    boot = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist)],
        check=False,
        capture_output=True,
        text=True,
    )
    if boot.returncode != 0:
        # Fall back to classic load.
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


def start_uvicorn_background() -> None:
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
            config.HOST,
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
    print(f"Started uvicorn pid {proc.pid} → http://{config.HOST}:{config.PORT}", flush=True)


def start_uvicorn_foreground() -> None:
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    print(f"Starting uvicorn on http://{config.HOST}:{config.PORT} (Ctrl+C to stop)", flush=True)
    os.execvpe(
        str(_venv_python()),
        [
            str(_venv_python()),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            config.HOST,
            "--port",
            str(config.PORT),
        ],
        env,
    )


def wait_for_health(*, seconds: float = 60.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if health_ok():
            print(f"Healthy: {HEALTH_URL}", flush=True)
            return True
        time.sleep(0.5)
    print(f"WARNING: health check did not pass within {seconds:.0f}s ({HEALTH_URL})", flush=True)
    return False


def stop_all() -> None:
    stop_launchd()
    stop_pidfile()
    # Best-effort: free the port if something else is bound.
    if health_ok(timeout=0.5):
        print(
            f"Something is still answering on {config.HOST}:{config.PORT}. "
            "Stop it manually if needed.",
            flush=True,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull Reading Buddy, refresh audio if needed, start the server."
    )
    p.add_argument("--no-pull", action="store_true", help="Skip git fetch/pull")
    p.add_argument("--no-audio", action="store_true", help="Skip audio stamp / regenerate")
    p.add_argument(
        "--force-audio",
        action="store_true",
        help="Force regenerate all generated wavs",
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
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os.chdir(ROOT)
    config.ensure_dirs()

    if args.stop:
        stop_all()
        return 0

    if not args.no_pull:
        git_pull()

    if not args.no_audio:
        maybe_regenerate_audio(force=args.force_audio)

    # Default: LaunchAgent on macOS; foreground uvicorn elsewhere.
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
        start_launchd()
        if not args.no_wait:
            wait_for_health()
        print(f"Open http://{config.HOST}:{config.PORT}", flush=True)
        return 0

    if mode == "background":
        start_uvicorn_background()
        if not args.no_wait:
            wait_for_health()
        print(f"Open http://{config.HOST}:{config.PORT}", flush=True)
        return 0

    # Foreground.
    if health_ok(timeout=0.3):
        print(
            f"Port {config.PORT} already looks healthy — "
            "reusing it. Pass --stop first to restart.",
            flush=True,
        )
        return 0
    start_uvicorn_foreground()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
