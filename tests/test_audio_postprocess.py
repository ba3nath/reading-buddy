"""Generated-clip postprocess should keep short-word plosives."""

from __future__ import annotations

import inspect

from app import audio_files
from app.audio_files import tts_render, tts_voice


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


def test_tts_voice_top_avoids_topi_release():
    """bf_isabella vowelizes top's /p/ → topi; alice keeps a clean stop."""
    voice, lang = tts_voice("top")
    assert voice == "bf_alice"
    assert lang == "en-gb"
    # Default words stay on the session voice.
    assert tts_voice("cup") == (None, None)
    spoken, speed = tts_render("top")
    assert spoken == "top."
    assert speed <= 0.88


def test_tts_render_can_avoids_cant_trailing_burst():
    """'can.' adds a second energy burst heard as can't / cantttt."""
    spoken, speed = tts_render("can")
    assert spoken == "can"
    assert not spoken.endswith(".")
    assert 0.94 <= speed <= 1.0


def test_tts_render_were_stays_were_not_was():
    """Isabella bare drifts to 'Worched'; lewis bare is Beginner-close 'Where?'."""
    spoken, speed = tts_render("were")
    assert spoken == "were"
    assert not spoken.endswith(".")
    assert speed >= 0.98
    voice, lang = tts_voice("were")
    assert voice == "bm_lewis"
    assert lang == "en-gb"


def test_tts_overrides_for_whisper_clear_words():
    """Spot-check overrides for clips Whisper often misheard."""
    assert tts_render("sheep") == ("a sheep", 0.95)
    assert tts_render("truck") == ("a truck", 0.95)
    assert tts_voice("truck") == ("bf_emma", "en-gb")
    assert tts_render("thin") == ("thin", 0.96)
    assert tts_voice("thin") == ("bf_alice", "en-gb")
    assert tts_render("pen") == ("pen!", 1.0)
    assert tts_voice("pen") == ("bf_alice", "en-gb")
    assert tts_voice("sit") == ("bf_alice", "en-gb")
