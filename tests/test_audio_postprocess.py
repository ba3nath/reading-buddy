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
    assert line == "the cat sat."
    assert line_speed == 0.90
    long_line, long_line_speed = tts_render("Jack and Jill went up the hill")
    assert long_line == "Jack and Jill went up the hill"
    assert long_line_speed == 0.95


def test_tts_render_avoids_logee_netee_trailing_syllable():
    """Period + slow Kokoro en-gb turns log/net into logee/netee."""
    log, log_speed = tts_render("log")
    assert log == "log"
    assert not log.endswith(".")
    assert 0.85 <= log_speed <= 0.95
    net, net_speed = tts_render("net")
    assert net == "net"
    assert not net.endswith(".")
    assert net_speed >= 0.94


def test_tts_render_avoids_a_and_bring_trailing_burst():
    """Period on bare 'a' / 'bring' adds a second energy burst (ay-uh / bring-uh)."""
    a, a_speed = tts_render("a")
    assert a == "a"
    assert not a.endswith(".")
    assert 0.85 <= a_speed <= 0.92
    bring, bring_speed = tts_render("bring")
    assert bring == "bring"
    assert not bring.endswith(".")
    assert 0.85 <= bring_speed <= 0.92


def test_tts_render_ng_is_not_treated_as_plosive_g():
    """bring/long end in /ŋ/, not a /g/ burst — don't crawl to 0.78."""
    # bring is bare (trailing-burst override); still must not use plosive 0.78.
    bring, bring_speed = tts_render("bring")
    assert bring == "bring"
    assert bring_speed >= 0.84
    long, long_speed = tts_render("long")
    assert long == "long."
    assert long_speed >= 0.84
    # Real plosive -g still slows.
    dog, dog_speed = tts_render("dog")
    assert dog == "dog."
    assert dog_speed <= 0.80


def test_tts_render_sit_keeps_unvoiced_s():
    """'sit.' @ slow speed voices the onset as /zIt/; bang + 1.0 keeps /s/."""
    spoken, speed = tts_render("sit")
    assert spoken == "sit!"
    assert speed >= 0.98
