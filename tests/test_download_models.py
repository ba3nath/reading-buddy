"""Atomic Kokoro download recovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "download_models", ROOT / "scripts" / "download_models.py"
)
assert SPEC and SPEC.loader
download_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(download_models)


def test_download_file_atomic_rename(tmp_path, monkeypatch):
    dest = tmp_path / "voices-v1.0.bin"
    calls: list[tuple[str, Path]] = []

    def fake_retrieve(url: str, path: str | Path) -> None:
        calls.append((url, Path(path)))
        Path(path).write_bytes(b"ok-data")

    monkeypatch.setattr(download_models.urllib.request, "urlretrieve", fake_retrieve)
    download_models.download_file("https://example.test/v.bin", dest)
    assert dest.read_bytes() == b"ok-data"
    assert not dest.with_name(dest.name + ".partial").exists()
    assert calls and str(calls[0][1]).endswith(".partial")


def test_download_file_cleans_partial_on_failure(tmp_path, monkeypatch):
    dest = tmp_path / "kokoro-v1.0.onnx"

    def fake_retrieve(url: str, path: str | Path) -> None:
        Path(path).write_bytes(b"partial")
        raise OSError("network dropped")

    monkeypatch.setattr(download_models.urllib.request, "urlretrieve", fake_retrieve)
    try:
        download_models.download_file("https://example.test/m.onnx", dest)
    except OSError:
        pass
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".partial").exists()


def test_download_file_skips_nonempty(tmp_path, monkeypatch):
    dest = tmp_path / "voices-v1.0.bin"
    dest.write_bytes(b"already")

    def boom(*_a, **_k):  # noqa: ANN001
        raise AssertionError("should not download")

    monkeypatch.setattr(download_models.urllib.request, "urlretrieve", boom)
    download_models.download_file("https://example.test/v.bin", dest)
    assert dest.read_bytes() == b"already"


def test_download_file_replaces_empty_stub(tmp_path, monkeypatch):
    dest = tmp_path / "voices-v1.0.bin"
    dest.write_bytes(b"")

    def fake_retrieve(url: str, path: str | Path) -> None:
        Path(path).write_bytes(b"full")

    monkeypatch.setattr(download_models.urllib.request, "urlretrieve", fake_retrieve)
    download_models.download_file("https://example.test/v.bin", dest)
    assert dest.read_bytes() == b"full"
