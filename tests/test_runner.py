"""runner.py helpers — no network / no uvicorn process required."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_parse_args_localhost_only_and_force_deps():
    args = runner.parse_args(["--localhost-only", "--force-deps", "--skip-deps"])
    assert args.localhost_only
    assert args.force_deps
    assert args.skip_deps


def test_find_system_python_returns_usable_interpreter():
    py = runner.find_system_python()
    assert py.is_file()


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
    calls: list[list[str]] = []

    class _Ok:
        returncode = 0

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        return _Ok()

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.ensure_deps(force=True) is True
    assert any("pip" in c for c in calls)
    stamp = json.loads((tmp_path / "deps.json").read_text(encoding="utf-8"))
    assert stamp["requirements_sha256"] == runner.file_digest(req)


def test_models_ready_requires_kokoro_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KOKORO_MODEL_PATH", tmp_path / "m.onnx")
    monkeypatch.setattr(config, "KOKORO_VOICES_PATH", tmp_path / "v.bin")
    assert runner.models_ready() is False
    (tmp_path / "m.onnx").write_bytes(b"x")
    (tmp_path / "v.bin").write_bytes(b"y")
    assert runner.models_ready() is True


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
