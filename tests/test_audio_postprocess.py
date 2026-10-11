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
    # cup uses a carrier; other short words still get period + slowdown.
    assert tts_render("cup") == ("the cup", 0.95)
    spoken_the, speed_the = tts_render("the")
    assert spoken_the == "the."
    assert speed_the <= 0.88
    pig, pig_speed = tts_render("pig")
    assert pig == "pig."
    assert pig_speed <= 0.80  # voiced plosive ending
    line, line_speed = tts_render("the cat sat")
    assert line == "the cat sat."
    assert line_speed == 0.90
    long_line, long_line_speed = tts_render("Jack and Jill went up the hill")
    assert long_line == "Jack and Jill went up the hill"
    assert long_line_speed == 0.95


def test_tts_render_avoids_logee_netee_trailing_syllable():
    """Bare period+slow turns log/net into logee/netee; both use carriers."""
    assert tts_render("log") == ("wooden log", 0.95)
    assert tts_voice("log") == ("bf_emma", "en-gb")
    assert tts_render("net") == ("the net", 0.95)
    assert tts_voice("net") == ("bf_emma", "en-gb")


def test_tts_render_avoids_a_and_bring_trailing_burst():
    """Period on bare 'a' adds a burst; bring uses a clear carrier phrase."""
    a, a_speed = tts_render("a")
    assert a == "a"
    assert not a.endswith(".")
    assert 0.85 <= a_speed <= 0.92
    assert tts_render("bring") == ("please bring", 0.95)
    assert tts_voice("bring") == ("bf_alice", "en-gb")


def test_tts_render_ng_is_not_treated_as_plosive_g():
    """bring/long end in /ŋ/, not a /g/ burst — don't crawl to 0.78."""
    bring, bring_speed = tts_render("bring")
    assert "bring" in bring
    assert bring_speed >= 0.84
    long, long_speed = tts_render("long")
    assert long == "long."
    assert long_speed >= 0.84
    # Real plosive -g still slows (unless a clarity override exists).
    pig, pig_speed = tts_render("pig")
    assert pig == "pig."
    assert pig_speed <= 0.80
    # dog uses a short carrier — bare Kokoro was misheard as "doggies".
    assert tts_render("dog") == ("a dog", 0.95)


def test_tts_render_sit_keeps_unvoiced_s():
    """Carrier 'please sit' + emma keeps /s/ (bare sit! still drifted)."""
    spoken, speed = tts_render("sit")
    assert spoken == "please sit"
    assert speed == 0.95
    assert tts_voice("sit") == ("bf_emma", "en-gb")


def test_tts_voice_top_avoids_topi_release():
    """Carrier 'on top' + emma — bare top often collapses for Whisper."""
    voice, lang = tts_voice("top")
    assert voice == "bf_emma"
    assert lang == "en-gb"
    assert tts_voice("cup") == ("bf_emma", "en-gb")
    spoken, speed = tts_render("top")
    assert spoken == "on top"
    assert speed == 0.95


def test_tts_render_can_avoids_cant_trailing_burst():
    """Bare 'can.' bursts to can't; carrier 'we can' is clear."""
    assert tts_render("can") == ("we can", 0.95)
    assert tts_voice("can") == ("bf_alice", "en-gb")


def test_tts_render_were_uses_carrier_phrase():
    """Bare 'were' → Where?; carrier 'they were' + lewis is clear."""
    spoken, speed = tts_render("were")
    assert spoken == "they were"
    assert speed == 0.95
    voice, lang = tts_voice("were")
    assert voice == "bm_lewis"
    assert lang == "en-gb"


def test_tts_overrides_for_whisper_clear_words():
    """Spot-check overrides for clips Whisper often misheard."""
    assert tts_render("sheep") == ("a sheep", 0.95)
    assert tts_render("truck") == ("a truck", 0.95)
    assert tts_voice("truck") == ("bf_emma", "en-gb")
    assert tts_render("thin") == ("so thin", 0.95)
    assert tts_voice("thin") == ("bf_emma", "en-gb")
    assert tts_voice("sheep") == ("bf_emma", "en-gb")
    assert tts_render("top") == ("on top", 0.95)
    assert tts_render("can") == ("we can", 0.95)
    assert tts_render("log") == ("wooden log", 0.95)
    assert tts_render("pen") == ("the pen", 0.95)
    assert tts_voice("pen") == ("bf_emma", "en-gb")
    assert tts_render("sit") == ("please sit", 0.95)
    assert tts_voice("sit") == ("bf_emma", "en-gb")
    assert tts_render("when") == ("say when", 0.95)
    assert tts_voice("when") == ("bf_alice", "en-gb")
    assert tts_render("cup") == ("the cup", 0.95)
    assert tts_voice("cup") == ("bf_emma", "en-gb")
    assert tts_render("cat") == ("fat cat", 0.95)
    assert tts_voice("cat") == ("bf_alice", "en-gb")
    assert tts_render("map") == ("a map", 0.95)
    assert tts_render("bring") == ("please bring", 0.95)
    assert tts_render("net") == ("the net", 0.95)
