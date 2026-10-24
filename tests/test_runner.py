"""runner.py helpers — no network / no uvicorn process required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import runner
from app import config


def test_audio_input_paths_cover_generation_surface():
    assert "app/audio_files.py" in runner.AUDIO_INPUT_PATHS
    assert "scripts/generate_audio.py" in runner.AUDIO_INPUT_PATHS
    assert "content/items.json" in runner.AUDIO_INPUT_PATHS
    for rel in runner.AUDIO_INPUT_PATHS:
        assert (runner.ROOT / rel).is_file(), rel


def test_audio_inputs_fingerprint_is_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "AUDIO_INPUT_PATHS",
        ("a.py", "b.json"),
    )
    (tmp_path / "a.py").write_text("hello", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    first = runner.audio_inputs_fingerprint()
    second = runner.audio_inputs_fingerprint()
    assert first == second
    assert len(first["a.py"]) == 64
    (tmp_path / "a.py").write_text("hello!", encoding="utf-8")
    third = runner.audio_inputs_fingerprint()
    assert third["a.py"] != first["a.py"]
    assert third["b.json"] == first["b.json"]


def test_stamp_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STAMP_PATH", tmp_path / "stamp.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    files = {"app/audio_files.py": "abc"}
    runner.save_stamp(files)
    assert runner.load_stamp() == files


def test_launchd_plist_body_contains_uvicorn_bind():
    body = runner.launchd_plist_body(Path("/tmp/venv/bin/python"), bind_host="0.0.0.0")
    assert runner.LAUNCHD_LABEL in body
    assert "uvicorn" in body
    assert "app.main:app" in body
    assert str(config.PORT) in body
    assert "0.0.0.0" in body
    assert "HF_HUB_OFFLINE" in body
    assert "<key>PATH</key>" in body
    assert "/opt/homebrew/bin" in body or "/usr/local/bin" in body


def test_parse_args_localhost_only_and_force_deps():
    args = runner.parse_args(["--localhost-only", "--force-deps", "--skip-deps"])
    assert args.localhost_only
    assert not args.lan
    assert args.force_deps
    assert args.skip_deps
    assert runner.resolve_bind_host(args) == "127.0.0.1"


def test_default_bind_is_localhost():
    args = runner.parse_args([])
    assert not args.lan
    assert not args.localhost_only
    assert runner.resolve_bind_host(args) == "127.0.0.1"


def test_lan_bind_opens_all_interfaces():
    args = runner.parse_args(["--lan"])
    assert args.lan
    assert runner.resolve_bind_host(args) == "0.0.0.0"


def test_lan_and_localhost_only_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        runner.parse_args(["--lan", "--localhost-only"])


def test_free_port_handles_missing_lsof(monkeypatch):
    def boom(*_a, **_k):  # noqa: ANN001
        raise FileNotFoundError("lsof")

    monkeypatch.setattr(runner.subprocess, "run", boom)
    runner._free_port()  # must not raise


def test_stop_all_warns_when_port_still_healthy(monkeypatch, capsys):
    monkeypatch.setattr(runner, "stop_launchd", lambda: None)
    monkeypatch.setattr(runner, "stop_pidfile", lambda: None)
    monkeypatch.setattr(runner, "_free_port", lambda: None)
    monkeypatch.setattr(runner.time, "sleep", lambda _s: None)
    monkeypatch.setattr(runner, "health_ok", lambda timeout=0.5: True)
    runner.stop_all()
    out = capsys.readouterr().out
    assert "still answering on port" in out


def test_find_system_python_returns_usable_interpreter():
    py = runner.find_system_python()
    assert py.is_file()
    version = runner._python_version([str(py)])
    assert version is not None
    assert runner._version_supported(version)


def test_python_version_bounds_reject_too_new():
    assert runner.MIN_PY == (3, 11)
    assert runner.MAX_PY == (3, 13)
    assert runner._version_supported((3, 12))
    assert runner._version_supported((3, 11))
    assert runner._version_supported((3, 13))
    assert not runner._version_supported((3, 10))
    assert not runner._version_supported((3, 14))
    assert not runner._version_supported((3, 15))


def test_requirements_and_pyproject_agree_on_python_band():
    req = (runner.ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = (runner.ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "ctranslate2" in req
    assert "onnxruntime" in req
    assert "kokoro-onnx" in req
    assert 'requires-python = ">=3.11,<3.14"' in pyproject
    assert "3.11" in req and "3.13" in req


def test_runtime_imports_list_covers_stack():
    for name in (
        "fastapi",
        "faster_whisper",
        "ctranslate2",
        "kokoro_onnx",
        "onnxruntime",
        "metaphone",
    ):
        assert name in runner.RUNTIME_IMPORTS


def test_ensure_venv_recreates_unsupported_interpreter(monkeypatch, tmp_path):
    venv_dir = tmp_path / ".venv"
    py_path = venv_dir / "bin" / "python"
    py_path.parent.mkdir(parents=True)
    py_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(runner, "_venv_dir", lambda: venv_dir)
    monkeypatch.setattr(runner, "_venv_python", lambda: py_path)
    monkeypatch.setattr(runner, "find_system_python", lambda: Path("/usr/bin/python3.12"))
    calls: list[list[str]] = []

    class _Ok:
        returncode = 0

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text("", encoding="utf-8")
        return _Ok()

    monkeypatch.setattr(runner, "_run", fake_run)

    def version_of(cmd):  # noqa: ANN001
        # Before recreate: unsupported. After _run created venv: supported.
        return (3, 12) if calls else (3, 15)

    monkeypatch.setattr(runner, "_python_version", version_of)
    out = runner.ensure_venv()
    assert out == py_path
    assert calls and "venv" in calls[0]


def test_maybe_regenerate_skips_when_stamp_matches(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STAMP_PATH", tmp_path / "stamp.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    fp = {"app/audio_files.py": "x" * 64}
    runner.save_stamp(fp)
    monkeypatch.setattr(runner, "audio_inputs_fingerprint", lambda: fp)
    monkeypatch.setattr(runner, "audio_ready", lambda: True)
    called: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        called.append(cmd)
        raise AssertionError("generate should not run")

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.maybe_regenerate_audio(force=False) is False
    assert called == []


def test_maybe_regenerate_forces_when_inputs_change(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STAMP_PATH", tmp_path / "stamp.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    runner.save_stamp({"app/audio_files.py": "old"})
    monkeypatch.setattr(
        runner,
        "audio_inputs_fingerprint",
        lambda: {"app/audio_files.py": "new"},
    )
    monkeypatch.setattr(runner, "audio_ready", lambda: True)
    calls: list[list[str]] = []

    class _Ok:
        returncode = 0

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        return _Ok()

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_venv_python", lambda: Path("/venv/bin/python"))
    assert runner.maybe_regenerate_audio(force=False) is True
    assert calls and "--force" in calls[0]
    stamp = json.loads((tmp_path / "stamp.json").read_text(encoding="utf-8"))
    assert stamp["files"]["app/audio_files.py"] == "new"


def test_parse_args_stop_and_flags():
    args = runner.parse_args(["--stop", "--force-audio"])
    assert args.stop
    assert args.force_audio


def test_ensure_deps_skips_when_stamp_and_imports_ok(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.1\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REQUIREMENTS", req)
    monkeypatch.setattr(runner, "DEPS_STAMP_PATH", tmp_path / "deps.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    digest = runner.file_digest(req)
    (tmp_path / "deps.json").write_text(
        json.dumps({"requirements_sha256": digest}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "verify_runtime_imports", lambda py=None: None)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        raise AssertionError("pip should not run")

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.ensure_deps(force=False) is False
    assert calls == []


def test_ensure_deps_runs_when_forced(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.1\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REQUIREMENTS", req)
    monkeypatch.setattr(runner, "DEPS_STAMP_PATH", tmp_path / "deps.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner, "_venv_python", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(runner, "_python_version", lambda cmd: (3, 12))
    monkeypatch.setattr(runner, "verify_runtime_imports", lambda py=None: None)
    calls: list[list[str]] = []

    class _Ok:
        returncode = 0

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        return _Ok()

    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    assert runner.ensure_deps(force=True) is True
    assert any("pip" in " ".join(c) for c in calls)
    stamp = json.loads((tmp_path / "deps.json").read_text(encoding="utf-8"))
    assert stamp["requirements_sha256"] == runner.file_digest(req)


def test_models_ready_requires_kokoro_and_whisper(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KOKORO_MODEL_PATH", tmp_path / "kokoro" / "m.onnx")
    monkeypatch.setattr(config, "KOKORO_VOICES_PATH", tmp_path / "kokoro" / "v.bin")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    assert runner.models_ready() is False
    (tmp_path / "kokoro").mkdir()
    (tmp_path / "kokoro" / "m.onnx").write_bytes(b"x")
    (tmp_path / "kokoro" / "v.bin").write_bytes(b"y")
    assert runner.kokoro_ready() is True
    assert runner.whisper_files_ready() is False
    assert runner.models_ready() is False
    whisper = tmp_path / "whisper-small.en"
    whisper.mkdir()
    (whisper / "config.json").write_text("{}", encoding="utf-8")
    assert runner.whisper_files_ready() is False  # config alone ≠ ready
    (whisper / "model.bin").write_bytes(b"weights")
    assert runner.whisper_files_ready() is True
    assert runner.models_ready() is True


def test_whisper_files_ready_detects_hf_cache_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    assert runner.whisper_files_ready() is False
    snap = (
        tmp_path
        / "models--Systran--faster-whisper-small.en"
        / "snapshots"
        / "abc"
    )
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"weights")
    assert runner.whisper_files_ready() is True


def test_lan_ips_returns_list():
    ips = runner.lan_ips()
    assert isinstance(ips, list)
    assert all(isinstance(ip, str) for ip in ips)


def test_health_url_uses_loopback():
    assert runner.health_url().startswith("http://127.0.0.1:")
    assert str(config.PORT) in runner.health_url()


def test_run_entrypoint_script_is_executable_shell():
    path = runner.ROOT / "run"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#!/")
    assert "runner.py" in text
    assert path.stat().st_mode & 0o111


def test_maybe_regenerate_illustrations_skips_when_keys_exist(monkeypatch):
    keys = runner.ROOT / "static" / "illustrations" / "keys.json"
    if not keys.is_file():
        return
    called: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        called.append(cmd)
        raise AssertionError("illustrations should not regenerate")

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.maybe_regenerate_illustrations() is False
    assert called == []


def test_maybe_regenerate_illustrations_runs_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "generate_illustrations.py"
    script.write_text("# stub\n", encoding="utf-8")
    (tmp_path / "static" / "illustrations").mkdir(parents=True)
    monkeypatch.setattr(runner, "_venv_python", lambda: Path("/venv/bin/python"))
    calls: list[list[str]] = []

    class _Ok:
        returncode = 0

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        return _Ok()

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.maybe_regenerate_illustrations() is True
    assert calls and "generate_illustrations.py" in calls[0][-1]


def test_print_ready_banner_mentions_parent_and_stop(capsys):
    runner.print_ready_banner(bind_host="0.0.0.0")
    out = capsys.readouterr().out
    assert "127.0.0.1" in out
    assert "/parent" in out
    assert "./run --stop" in out


def test_print_ready_banner_localhost_mentions_lan_flag(capsys):
    runner.print_ready_banner(bind_host="127.0.0.1")
    out = capsys.readouterr().out
    assert "--lan" in out
    assert "Same Wi‑Fi" not in out


def test_main_stop_returns_zero(monkeypatch):
    stopped: list[bool] = []

    def fake_stop() -> None:
        stopped.append(True)

    monkeypatch.setattr(runner, "stop_all", fake_stop)
    assert runner.main(["--stop"]) == 0
    assert stopped == [True]


def test_ensure_deps_runs_when_requirements_hash_changes(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.1\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REQUIREMENTS", req)
    monkeypatch.setattr(runner, "DEPS_STAMP_PATH", tmp_path / "deps.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "deps.json").write_text(
        json.dumps({"requirements_sha256": "old" * 16}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "_venv_python", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(runner, "_python_version", lambda cmd: (3, 12))
    monkeypatch.setattr(runner, "verify_runtime_imports", lambda py=None: None)
    calls: list[list[str]] = []

    class _Ok:
        returncode = 0

    monkeypatch.setattr(runner, "_run", lambda cmd, **k: calls.append(cmd) or _Ok())
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    assert runner.ensure_deps(force=False) is True
    assert any("requirements.txt" in " ".join(c) for c in calls)
