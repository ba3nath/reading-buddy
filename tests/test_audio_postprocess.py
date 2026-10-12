"""Generated-clip postprocess should keep short-word plosives."""

from __future__ import annotations

import inspect

from app import audio_files
from app.audio_files import (
    _TTS_WORD_OVERRIDES,
    spoken_matches_target,
    tts_render,
    tts_voice,
)


def test_postprocess_keeps_tail_plosives():
    src = inspect.getsource(audio_files.postprocess_generated_wav)
    # Lead trim only — stop_periods= eats /p/ /t/ on cup/map/cat.
    assert "silenceremove=start_periods=1" in src
    assert "stop_periods=" not in src
    assert "apad" in src
    assert "adelay" in src
    assert "pad_dur=0.28" in src or "0.28" in src


def test_tts_overrides_never_add_extra_words():
    """Kids hear the clip — spoken text must be only the on-screen word."""
    for word, (spoken, _speed) in _TTS_WORD_OVERRIDES.items():
        assert spoken_matches_target(word, spoken), (word, spoken)
        rendered, _ = tts_render(word)
        assert spoken_matches_target(word, rendered), (word, rendered)


def test_tts_render_lengthens_short_words():
    spoken, speed = tts_render("cup")
    assert spoken_matches_target("cup", spoken)
    assert spoken.endswith(".")
    assert speed < 1.0
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
    """Period + slow can turn log/net into logee/netee — tuned bare forms."""
    log, log_speed = tts_render("log")
    assert log == "log"
    assert not log.endswith(".")
    assert 0.90 <= log_speed <= 0.95
    assert tts_voice("log") == ("bf_emma", "en-gb")
    net, net_speed = tts_render("net")
    assert net == "net!"
    assert net_speed >= 0.98
    assert tts_voice("net") == ("bf_alice", "en-gb")


def test_tts_render_avoids_a_and_bring_trailing_burst():
    """Period on bare 'a' adds a burst; bring stays a single token."""
    a, a_speed = tts_render("a")
    assert a == "a"
    assert not a.endswith(".")
    assert 0.85 <= a_speed <= 0.92
    bring, bring_speed = tts_render("bring")
    assert bring == "bring"
    assert spoken_matches_target("bring", bring)
    assert bring_speed >= 0.88
    assert tts_voice("bring") == ("bf_emma", "en-gb")


def test_tts_render_ng_is_not_treated_as_plosive_g():
    """bring/long end in /ŋ/, not a /g/ burst — don't crawl to 0.78."""
    bring, bring_speed = tts_render("bring")
    assert bring == "bring"
    assert bring_speed >= 0.84
    long, long_speed = tts_render("long")
    assert long == "long."
    assert long_speed >= 0.84
    pig, pig_speed = tts_render("pig")
    assert pig == "pig."
    assert pig_speed <= 0.80
    dog, dog_speed = tts_render("dog")
    assert dog == "dog."
    assert spoken_matches_target("dog", dog)
    assert dog_speed == 0.88


def test_tts_render_sit_keeps_unvoiced_s():
    """'sit!' + alice keeps /s/ better than slow 'sit.'."""
    spoken, speed = tts_render("sit")
    assert spoken == "sit!"
    assert speed >= 0.98
    assert tts_voice("sit") == ("bf_alice", "en-gb")


def test_tts_voice_top_avoids_topi_release():
    """emma + period — bare top often collapses; still only says 'top'."""
    voice, lang = tts_voice("top")
    assert voice == "bf_emma"
    assert lang == "en-gb"
    spoken, speed = tts_render("top")
    assert spoken == "top."
    assert spoken_matches_target("top", spoken)
    assert speed == 0.90


def test_tts_render_can_avoids_cant_trailing_burst():
    """Bare 'can.' bursts to can't; bare 'can' @ ~0.96 is cleaner."""
    spoken, speed = tts_render("can")
    assert spoken == "can"
    assert not spoken.endswith(".")
    assert 0.94 <= speed <= 1.0
    assert tts_voice("can") == ("bf_alice", "en-gb")


def test_tts_render_were_stays_single_word():
    """Were must play as 'were', never 'they were'."""
    spoken, speed = tts_render("were")
    assert spoken == "were"
    assert spoken_matches_target("were", spoken)
    assert speed >= 0.98
    assert tts_voice("were") == ("bm_lewis", "en-gb")


def test_tts_render_cat_is_only_cat():
    """Regression: never play 'fat cat' when the screen says cat."""
    spoken, speed = tts_render("cat")
    assert spoken == "cat!"
    assert spoken_matches_target("cat", spoken)
    assert speed >= 0.98
    assert tts_voice("cat") == ("bf_emma", "en-gb")


def test_tts_overrides_for_whisper_clear_words():
    """Spot-check single-word overrides for clips Whisper often misheard."""
    assert tts_render("sheep") == ("sheep.", 0.88)
    assert tts_render("truck") == ("truck.", 0.85)
    assert tts_voice("truck") == ("bf_emma", "en-gb")
    assert tts_render("thin") == ("thin!", 1.0)
    assert tts_voice("thin") == ("bf_emma", "en-gb")
    assert tts_render("pen") == ("pen.", 0.88)
    assert tts_voice("pen") == ("bf_emma", "en-gb")
    assert tts_render("when") == ("when.", 0.92)
    assert tts_voice("when") == ("bf_emma", "en-gb")
    assert tts_render("cup") == ("cup.", 0.88)
    assert tts_voice("cup") == ("bf_emma", "en-gb")
    assert tts_render("net") == ("net!", 1.0)
