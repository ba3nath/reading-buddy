"""Generated-clip postprocess should not aggressively clip plosives."""

from __future__ import annotations

import inspect

from app import audio_files


def test_postprocess_filter_is_gentle():
    src = inspect.getsource(audio_files.postprocess_generated_wav)
    assert "silenceremove" in src
    # Must keep pad so short words like "cat" are not edge-clipped.
    assert "apad" in src or "adelay" in src
    # Threshold should be quieter than the old -40dB default.
    assert "-50dB" in src
    assert "start_threshold=-40dB" not in src
    assert "stop_threshold=-40dB" not in src
