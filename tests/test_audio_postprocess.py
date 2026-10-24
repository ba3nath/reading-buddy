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
    # Pads after loudnorm so silence doesn't crush quiet plosive tails.
    assert src.index("loudnorm=") < src.index("adelay=")
    assert src.index("loudnorm=") < src.index("apad=")
    assert "pad_dur={_LISTEN_TRAIL_SEC}" in src or "pad_dur=0.5" in src
    assert "_LISTEN_LEAD_MS" in src
    assert audio_files._LISTEN_LEAD_MS >= 300
    assert audio_files._LISTEN_TRAIL_SEC >= 0.45


def test_postprocess_pads_after_loudnorm_not_before():
    """Regression: pad-before-loudnorm made short words sound clipped."""
    src = inspect.getsource(audio_files.postprocess_generated_wav)
    loud = src.index("loudnorm=")
    delay = src.index("adelay=")
    pad = src.index("apad=")
    assert loud < delay < pad


def test_tts_overrides_never_add_extra_words():
    """Kids hear the clip — spoken text must be only the on-screen word."""
    for word, (spoken, _speed) in _TTS_WORD_OVERRIDES.items():
        assert spoken_matches_target(word, spoken), (word, spoken)
        rendered, _ = tts_render(word)
        assert spoken_matches_target(word, rendered), (word, rendered)


def test_tts_render_lengthens_short_words():
    spoken, speed = tts_render("cup")
    assert spoken_matches_target("cup", spoken)
    assert spoken == "cup!"
    assert speed == 1.0
    spoken_the, speed_the = tts_render("the")
    assert spoken_the == "the!"
    assert speed_the == 0.95
    pig, pig_speed = tts_render("pig")
    assert pig == "pig"
    assert pig_speed == 0.86
    line, line_speed = tts_render("the cat sat")
    # Short phrases: no forced period (avoids trailing-syllable smear).
    assert line == "the cat sat"
    assert line_speed == 0.86
    assert tts_voice("the cat sat") == ("bf_emma", "en-gb")
    pig_phrase, pig_phrase_speed = tts_render("one small pig")
    assert pig_phrase == "one small pig"
    assert pig_phrase_speed == 1.0  # phrase-final /g/ — Alice, fast release
    assert tts_voice("one small pig") == ("bf_alice", "en-gb")
    assert tts_render("the green frog") == ("the green frog", 1.0)
    assert tts_voice("the green frog") == ("bf_alice", "en-gb")
    assert tts_render("frog") == ("frog.", 0.94)
    assert tts_voice("frog") == ("bf_emma", "en-gb")
    long_line, long_line_speed = tts_render("Jack and Jill went up the hill")
    assert long_line == "Jack and Jill went up the hill"
    assert long_line_speed == 0.90
    assert tts_voice("Jack and Jill went up the hill") == ("bf_emma", "en-gb")


def test_hot_sun_phrase_uses_alice_so_sun_stays_sun():
    """Isabella renders final sun as sunge/sandy. Alice keeps the word."""
    for text in ("The hot sun", "A hot sun", "a hot sun"):
        spoken, speed = tts_render(text)
        assert spoken.rstrip(".!?").lower() == text.lower()
        assert speed == 0.86
        assert tts_voice(text) == ("bf_alice", "en-gb")


def test_tts_render_log_and_net_whisper_winners():
    """log bare @0.82 alice (no vlog/logger); net keeps prior winner."""
    log, log_speed = tts_render("log")
    assert log == "log"
    assert log_speed == 0.82
    assert tts_voice("log") == ("bf_alice", "en-gb")
    net, net_speed = tts_render("net")
    assert net == "net."
    assert net_speed == 0.82
    assert tts_voice("net") == (None, None)


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
    assert pig == "pig"
    assert pig_speed == 0.86
    dog, dog_speed = tts_render("dog")
    assert dog == "dog."
    assert spoken_matches_target("dog", dog)
    assert dog_speed == 0.86
    assert tts_voice("frog") == ("bf_emma", "en-gb")
    assert tts_render("frog") == ("frog.", 0.94)


def test_tts_render_sit_keeps_unvoiced_s():
    """'sit!' + alice keeps /s/ better than slow 'sit.'."""
    spoken, speed = tts_render("sit")
    assert spoken == "sit!"
    assert speed >= 0.98
    assert tts_voice("sit") == ("bf_alice", "en-gb")


def test_tts_voice_top_avoids_topi_release():
    """bm_lewis + period — batch winner still only says 'top'."""
    voice, lang = tts_voice("top")
    assert voice == "bm_lewis"
    assert lang == "en-gb"
    spoken, speed = tts_render("top")
    assert spoken == "top."
    assert spoken_matches_target("top", spoken)
    assert speed == 0.88


def test_tts_render_can_whisper_winner():
    """Batch A/B: 'can!' @0.95 emma — still only the on-screen word."""
    spoken, speed = tts_render("can")
    assert spoken == "can!"
    assert spoken_matches_target("can", spoken)
    assert speed == 0.95
    assert tts_voice("can") == ("bf_emma", "en-gb")


def test_tts_render_were_stays_single_word():
    """Were must play as 'were', never 'they were'."""
    spoken, speed = tts_render("were")
    assert spoken == "were."
    assert spoken_matches_target("were", spoken)
    assert speed == 0.78
    assert tts_voice("were") == ("bm_lewis", "en-gb")


def test_tts_render_cat_is_only_cat():
    """Regression: never play 'fat cat' when the screen says cat."""
    spoken, speed = tts_render("cat")
    assert spoken == "cat."
    assert spoken_matches_target("cat", spoken)
    assert speed == 0.94
    assert tts_voice("cat") == ("bf_emma", "en-gb")


def test_tts_overrides_for_whisper_clear_words():
    """Spot-check single-word overrides from the batch Whisper A/B winners."""
    assert tts_render("sheep") == ("sheep.", 0.94)
    assert tts_render("truck") == ("truck.", 0.88)
    assert tts_voice("truck") == ("bm_lewis", "en-gb")
    assert tts_render("thin") == ("thin!", 1.0)
    assert tts_voice("thin") == ("bf_emma", "en-gb")
    assert tts_render("pen") == ("pen.", 0.94)
    assert tts_voice("pen") == ("bf_emma", "en-gb")
    assert tts_render("when") == ("when!", 1.0)
    assert tts_voice("when") == ("bm_lewis", "en-gb")
    assert tts_render("cup") == ("cup!", 1.0)
    assert tts_voice("cup") == ("bf_emma", "en-gb")
    assert tts_render("net") == ("net.", 0.82)
    assert tts_render("bed") == ("bed.", 0.88)
    assert tts_voice("bed") == ("bf_emma", "en-gb")
    assert tts_render("clock") == ("clock!", 0.95)
    assert tts_render("jam") == ("jam.", 0.82)
    assert tts_render("trap") == ("trap", 0.94)
    assert tts_voice("trap") == ("bf_emma", "en-gb")
    assert tts_render("bus") == ("bus", 1.0)
    assert tts_voice("bus") == ("bf_emma", "en-gb")
    assert tts_render("spoon") == ("spoon?", 0.92)
    assert tts_render("they") == ("they.", 0.82)
    assert tts_voice("they") == ("bf_emma", "en-gb")
    # Set 6–8 A/B winners (review pass)
    assert tts_render("all") == ("all.", 0.94)
    assert tts_voice("all") == ("bf_emma", "en-gb")
    assert tts_render("win") == ("win!", 0.95)
    assert tts_voice("win") == ("bf_alice", "en-gb")
    assert tts_render("what") == ("what.", 0.88)
    assert tts_render("your") == ("your.", 0.78)
    assert tts_render("would") == ("would", 0.88)
    assert tts_voice("would") == ("bf_emma", "en-gb")
    assert tts_render("drum") == ("drum.", 0.94)
    assert tts_voice("drum") == ("bf_emma", "en-gb")
    assert tts_voice("clock") == ("bf_emma", "en-gb")
    assert tts_voice("chair") == ("bm_lewis", "en-gb")
    assert tts_voice("fox") == ("bf_emma", "en-gb")
    # Short phrases use Emma by default (avoids trailing-syllable smear).
    assert tts_voice("two wet ducks") == ("bf_emma", "en-gb")
    assert tts_render("two wet ducks") == ("two wet ducks", 0.86)
    assert tts_render("one small pig") == ("one small pig", 1.0)
    assert tts_voice("one small pig") == ("bf_alice", "en-gb")
    assert tts_voice("Rain rain go away") == ("bf_emma", "en-gb")
    assert tts_render("Rain rain go away") == ("rain rain go away", 0.90)
