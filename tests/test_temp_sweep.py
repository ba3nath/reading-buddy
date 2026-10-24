"""Orphan data/tmp cleanup on startup."""

from __future__ import annotations

from app import config
from app.audio_files import sweep_temp_dir


def test_sweep_temp_dir_removes_orphans_keeps_warmup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEMP_DIR", tmp_path)
    (tmp_path / "warmup-silence.wav").write_bytes(b"warm")
    (tmp_path / "abc.webm").write_bytes(b"orphan")
    (tmp_path / "abc.wav").write_bytes(b"orphan")
    removed = sweep_temp_dir()
    assert removed == 2
    assert (tmp_path / "warmup-silence.wav").is_file()
    assert not (tmp_path / "abc.webm").exists()
    assert not (tmp_path / "abc.wav").exists()


def test_sweep_temp_dir_noop_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TEMP_DIR", tmp_path / "nope")
    assert sweep_temp_dir() == 0
