"""Backup includes progress DB and parent voice overrides."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "backup_data", ROOT / "scripts" / "backup_data.py"
)
assert SPEC and SPEC.loader
backup_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_data)


def test_backup_includes_human_voice(tmp_path, monkeypatch):
    data = tmp_path / "data"
    human = tmp_path / "human"
    kept = data / "kept"
    data.mkdir()
    human.mkdir()
    kept.mkdir()
    (data / "reading.db").write_bytes(b"sqlite")
    (data / "settings.json").write_text("{}", encoding="utf-8")
    (human / "cat.wav").write_bytes(b"RIFF humancat")
    (kept / "1.wav").write_bytes(b"RIFF kept")

    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "DB_PATH", data / "reading.db")
    monkeypatch.setattr(config, "KEPT_DIR", kept)
    monkeypatch.setattr(config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(backup_data.config, "DATA_DIR", data)
    monkeypatch.setattr(backup_data.config, "DB_PATH", data / "reading.db")
    monkeypatch.setattr(backup_data.config, "KEPT_DIR", kept)
    monkeypatch.setattr(backup_data.config, "AUDIO_HUMAN", human)

    out = tmp_path / "b.zip"
    backup_data.backup(out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "reading.db" in names
    assert "settings.json" in names
    assert "kept/1.wav" in names
    assert "human/cat.wav" in names
