"""Dependency / Python-band contracts for Windows and macOS installs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import runner
from app import config

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_pyproject_requires_python_matches_runner_bounds():
    match = re.search(r'requires-python\s*=\s*"([^"]+)"', PYPROJECT)
    assert match, "pyproject.toml must declare requires-python"
    assert match.group(1) == ">=3.11,<3.14"
    assert runner.MIN_PY == (3, 11)
    assert runner.MAX_PY == (3, 13)


def test_requirements_pins_critical_packages_with_upper_bounds():
    required = {
        "fastapi": True,
        "uvicorn": True,
        "faster-whisper": True,
        "ctranslate2": True,
        "onnxruntime": True,
        "kokoro-onnx": True,
        "metaphone": True,
        "soundfile": True,
        "numpy": True,
        "httpx": True,
        "pydantic": True,
        "pytest": True,
        "python-multipart": True,
    }
    for name in required:
        assert name in REQUIREMENTS, name
    # Upper bounds keep pip from dragging in broken majors on fresh Windows installs.
    assert "ctranslate2>=4.0,<5" in REQUIREMENTS
    assert "faster-whisper>=1.0.3,<2" in REQUIREMENTS
    assert "onnxruntime>=1.16.0,<2" in REQUIREMENTS
    assert "kokoro-onnx>=0.4.0,<1" in REQUIREMENTS
    assert "numpy>=1.26.0,<3" in REQUIREMENTS


def test_requirements_header_documents_python_band():
    head = "\n".join(REQUIREMENTS.splitlines()[:6]).lower()
    assert "3.11" in head
    assert "3.13" in head
    assert "kokoro" in head or "ctranslate2" in head


def test_runtime_imports_are_importable_in_project_venv():
    """Smoke: the active test interpreter can import the declared stack."""
    runner.verify_runtime_imports()


def test_pip_check_clean():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_python_install_hint_mentions_delete_venv_and_312():
    hint = runner._python_install_hint()
    assert "3.12" in hint
    assert ".venv" in hint


def test_find_system_python_errors_when_only_unsupported(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner.sys, "executable", "/opt/python3.15/bin/python")
    monkeypatch.setattr(
        runner,
        "_python_version",
        lambda cmd: (3, 15) if "3.15" in " ".join(cmd) or cmd[0].endswith("python") else None,
    )
    # sys.executable path also probed — always report 3.15.
    monkeypatch.setattr(runner, "_python_version", lambda cmd: (3, 15))
    with pytest.raises(RuntimeError, match="3.11"):
        runner.find_system_python()


def test_find_system_python_prefers_312_over_313(monkeypatch, tmp_path):
    py312 = tmp_path / "python3.12"
    py313 = tmp_path / "python3.13"
    py312.write_text("", encoding="utf-8")
    py313.write_text("", encoding="utf-8")

    def which(name: str) -> str | None:
        return {
            "python3.12": str(py312),
            "python3.13": str(py313),
        }.get(name)

    def version_of(cmd: list[str]):
        joined = " ".join(str(c) for c in cmd)
        if "python3.12" in joined or str(py312) in joined:
            return (3, 12)
        if "python3.13" in joined or str(py313) in joined:
            return (3, 13)
        return None

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        joined = " ".join(str(c) for c in cmd)
        if "sys.executable" in joined:
            path = str(py312) if "python3.12" in joined else str(py313)
            return type("R", (), {"returncode": 0, "stdout": path + "\n", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "\n", "stderr": ""})()

    monkeypatch.setattr(runner.shutil, "which", which)
    monkeypatch.setattr(runner, "_python_version", version_of)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner.sys, "executable", str(py313))
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    assert runner.find_system_python().resolve() == py312.resolve()


def test_ensure_deps_rejects_unsupported_venv_python(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.1\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REQUIREMENTS", req)
    monkeypatch.setattr(runner, "DEPS_STAMP_PATH", tmp_path / "deps.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner, "_venv_python", lambda: tmp_path / "py")
    monkeypatch.setattr(runner, "_python_version", lambda cmd: (3, 15))
    monkeypatch.setattr(runner, "verify_runtime_imports", lambda py=None: (_ for _ in ()).throw(RuntimeError("missing")))
    with pytest.raises(RuntimeError, match="3.15|3.11|too new|Need Python"):
        runner.ensure_deps(force=True)


def test_ensure_deps_wraps_pip_failure(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.1\n", encoding="utf-8")
    monkeypatch.setattr(runner, "REQUIREMENTS", req)
    monkeypatch.setattr(runner, "DEPS_STAMP_PATH", tmp_path / "deps.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runner, "_venv_python", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(runner, "_python_version", lambda cmd: (3, 12))
    monkeypatch.setattr(runner, "verify_runtime_imports", lambda py=None: None)

    def boom(cmd, **kwargs):  # noqa: ANN001
        raise runner.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(runner, "_run", boom)
    with pytest.raises(RuntimeError, match="pip install failed|ctranslate2|3.12"):
        runner.ensure_deps(force=True)


def test_verify_runtime_imports_raises_on_failure(monkeypatch):
    def fail_run(*args, **kwargs):  # noqa: ANN001
        raise runner.subprocess.CalledProcessError(
            1, args[0], stderr="ModuleNotFoundError: ctranslate2"
        )

    monkeypatch.setattr(runner.subprocess, "run", fail_run)
    with pytest.raises(RuntimeError, match="import check failed|ctranslate2"):
        runner.verify_runtime_imports("/fake/python")


def test_ensure_models_skips_when_ready(monkeypatch):
    monkeypatch.setattr(runner, "models_ready", lambda: True)
    called: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        called.append(cmd)
        raise AssertionError("download should not run")

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.ensure_models() is False
    assert called == []


def test_ensure_models_runs_download_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "KOKORO_MODEL_PATH", tmp_path / "m.onnx")
    monkeypatch.setattr(config, "KOKORO_VOICES_PATH", tmp_path / "v.bin")
    monkeypatch.setattr(runner, "_venv_python", lambda: Path("/venv/bin/python"))
    state = {"n": 0}

    class _Ok:
        returncode = 0

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        state["n"] += 1
        (tmp_path / "m.onnx").write_bytes(b"x")
        (tmp_path / "v.bin").write_bytes(b"y")
        return _Ok()

    monkeypatch.setattr(runner, "_run", fake_run)
    assert runner.ensure_models() is True
    assert state["n"] == 1
