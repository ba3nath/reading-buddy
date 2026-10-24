"""Backup includes progress DB and parent voice overrides; restore is safe."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

from app import config

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "backup_data", ROOT / "scripts" / "backup_data.py"
)
assert SPEC and SPEC.loader
backup_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_data)


def _point_backup_at(tmp_path, monkeypatch):
    data = tmp_path / "data"
    human = tmp_path / "human"
    kept = data / "kept"
    data.mkdir()
    human.mkdir()
    kept.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "DB_PATH", data / "reading.db")
    monkeypatch.setattr(config, "KEPT_DIR", kept)
    monkeypatch.setattr(config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(backup_data.config, "DATA_DIR", data)
    monkeypatch.setattr(backup_data.config, "DB_PATH", data / "reading.db")
    monkeypatch.setattr(backup_data.config, "KEPT_DIR", kept)
    monkeypatch.setattr(backup_data.config, "AUDIO_HUMAN", human)
    monkeypatch.setattr(backup_data, "ROOT", tmp_path)
    return data, human, kept


def test_backup_includes_human_voice(tmp_path, monkeypatch):
    data, human, kept = _point_backup_at(tmp_path, monkeypatch)
    (data / "reading.db").write_bytes(b"sqlite")
    (data / "settings.json").write_text("{}", encoding="utf-8")
    (human / "cat.wav").write_bytes(b"RIFF humancat")
    (kept / "1.wav").write_bytes(b"RIFF kept")

    out = tmp_path / "b.zip"
    backup_data.backup(out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "reading.db" in names
    assert "settings.json" in names
    assert "kept/1.wav" in names
    assert "human/cat.wav" in names


def test_restore_into_fresh_data_dir(tmp_path, monkeypatch):
    src_root = tmp_path / "src"
    src_root.mkdir()
    data, human, kept = _point_backup_at(src_root, monkeypatch)
    (data / "reading.db").write_bytes(b"sqlite-fresh")
    (data / "settings.json").write_text('{"mode":"beginner"}', encoding="utf-8")
    (human / "cat.wav").write_bytes(b"RIFF humancat")
    (kept / "9.wav").write_bytes(b"RIFF kept")
    zip_path = tmp_path / "roundtrip.zip"
    backup_data.backup(zip_path)

    dest = tmp_path / "dest"
    dest.mkdir()
    data2, human2, kept2 = _point_backup_at(dest, monkeypatch)
    assert not (data2 / "reading.db").exists()
    backup_data.restore(zip_path, force=False)
    assert (data2 / "reading.db").read_bytes() == b"sqlite-fresh"
    assert (data2 / "settings.json").read_text(encoding="utf-8") == '{"mode":"beginner"}'
    assert (human2 / "cat.wav").read_bytes() == b"RIFF humancat"
    assert (kept2 / "9.wav").read_bytes() == b"RIFF kept"


def test_restore_refuses_without_force(tmp_path, monkeypatch):
    data, human, kept = _point_backup_at(tmp_path, monkeypatch)
    (data / "reading.db").write_bytes(b"original-db")
    (data / "settings.json").write_text("{}", encoding="utf-8")
    (human / "a.wav").write_bytes(b"RIFF a")
    zip_path = tmp_path / "b.zip"
    backup_data.backup(zip_path)

    (data / "reading.db").write_bytes(b"existing-db!!!!")
    with pytest.raises(SystemExit) as exc:
        backup_data.restore(zip_path, force=False)
    assert exc.value.code == 2
    assert (data / "reading.db").read_bytes() == b"existing-db!!!!"


def test_restore_force_overwrites(tmp_path, monkeypatch):
    data, human, _kept = _point_backup_at(tmp_path, monkeypatch)
    (data / "reading.db").write_bytes(b"backup-bytes")
    (data / "settings.json").write_text('{"ok":1}', encoding="utf-8")
    (human / "x.wav").write_bytes(b"RIFF x")
    zip_path = tmp_path / "b.zip"
    backup_data.backup(zip_path)

    (data / "reading.db").write_bytes(b"dirty")
    (data / "settings.json").write_text("{}", encoding="utf-8")
    backup_data.restore(zip_path, force=True)
    assert (data / "reading.db").read_bytes() == b"backup-bytes"
    assert (data / "settings.json").read_text(encoding="utf-8") == '{"ok":1}'
    assert (human / "x.wav").read_bytes() == b"RIFF x"
