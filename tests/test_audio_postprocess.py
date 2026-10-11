"""Generated-clip postprocess should keep short-word plosives."""

from __future__ import annotations

import inspect

from app import audio_files
from app.audio_files import tts_render


def test_postprocess_keeps_tail_plosives():
    src = inspect.getsource(audio_files.postprocess_generated_wav)
    # Lead trim only — stop_periods= eats /p/ /t/ on cup/map/cat.
    assert "silenceremove=start_periods=1" in src
    assert "stop_periods=" not in src
    assert "apad" in src
    assert "adelay" in src
    assert "pad_dur=0.28" in src or "0.28" in src


def test_tts_render_lengthens_short_words():
    spoken, speed = tts_render("cup")
    assert spoken.endswith(".")
    assert speed < 1.0
    spoken_the, speed_the = tts_render("the")
    assert spoken_the == "the."
    assert speed_the <= 0.88
    dog, dog_speed = tts_render("dog")
    assert dog == "dog."
    assert dog_speed <= 0.80  # voiced plosive ending
    line, line_speed = tts_render("the cat sat")
    assert line == "the cat sat"
    assert line_speed <= 1.0
