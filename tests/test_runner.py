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
    body = runner.launchd_plist_body(Path("/tmp/venv/bin/python"))
    assert runner.LAUNCHD_LABEL in body
    assert "uvicorn" in body
    assert "app.main:app" in body
    assert str(config.PORT) in body
    assert config.HOST in body
    assert "HF_HUB_OFFLINE" in body


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
    args = runner.parse_args(["--stop", "--no-pull", "--force-audio"])
    assert args.stop
    assert args.no_pull
    assert args.force_audio
