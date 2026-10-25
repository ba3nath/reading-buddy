"""Generated-clip postprocess + natural-pacing TTS contracts."""

from __future__ import annotations

import array
import inspect
import math

from app import audio_files, config
from app.audio_files import (
    _TTS_WORD_OVERRIDES,
    spoken_matches_target,
    tighten_tail_samples,
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
    assert "tighten_tail_samples" in src
    assert src.index("loudnorm=") < src.index("adelay=")
    assert src.index("loudnorm=") < src.index("apad=")
    assert "_LISTEN_LEAD_MS" in src
    assert audio_files._LISTEN_LEAD_MS >= 300
    assert audio_files._LISTEN_TRAIL_SEC >= 0.45
    assert audio_files._TAIL_FADE_MS >= 50
    assert audio_files._TAIL_HANGOVER_MS >= 80
    assert "I=-16" in src
    assert "16000" not in src
    assert config.AUDIO_SAMPLE_RATE == 24000


def test_postprocess_pads_after_loudnorm_not_before():
    """Regression: pad-before-loudnorm made short words sound clipped."""
    src = inspect.getsource(audio_files.postprocess_generated_wav)
    loud = src.index("loudnorm=")
    delay = src.index("adelay=")
    pad = src.index("apad=")
    assert loud < delay < pad


def test_tighten_tail_cuts_smear_keeps_body():
    """Synthetic speech + quiet smear: cut removes smear, keeps body energy."""
    rate = 24000
    body_n = int(rate * 0.40)
    smear_n = int(rate * 0.25)
    samples = array.array("h")
    for i in range(body_n):
        # ~440 Hz tone at moderate level
        samples.append(int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
    for _ in range(smear_n):
        samples.append(200)  # quiet smear tail
    out = tighten_tail_samples(samples, rate, hangover_ms=50, fade_ms=40)
    assert len(out) < len(samples)
    assert len(out) >= int(body_n * 0.9)
    # Final samples near zero after fade
    assert abs(out[-1]) <= abs(out[body_n // 2])


def test_default_voice_is_emma():
    assert config.KOKORO_VOICE_ID == "bf_emma"


def test_tts_overrides_never_add_extra_words():
    """Kids hear the clip — spoken text must be only the on-screen word."""
    for word, (spoken, speed) in _TTS_WORD_OVERRIDES.items():
        assert spoken_matches_target(word, spoken), (word, spoken)
        assert speed >= 0.92, (word, speed)  # no crawl-speed overrides
        rendered, _ = tts_render(word)
        assert spoken_matches_target(word, rendered), (word, rendered)


def test_tts_render_uses_natural_pacing():
    """Default single words and phrases stay near spoken speed."""
    spoken, speed = tts_render("cup")
    assert spoken_matches_target("cup", spoken)
    assert spoken == "cup!"
    assert speed == 1.0

    spoken_bell, speed_bell = tts_render("bell")
    assert spoken_bell == "bell."
    assert speed_bell == 0.95

    pig, pig_speed = tts_render("pig")
    assert pig == "pig"
    assert pig_speed == 0.95
    assert tts_voice("pig") == ("bm_lewis", "en-gb")

    line, line_speed = tts_render("the cat sat")
    assert line == "the cat sat"
    assert line_speed == 0.95
    assert tts_voice("the cat sat") == ("bf_emma", "en-gb")

    pig_phrase, pig_phrase_speed = tts_render("one small pig")
    assert pig_phrase == "one small pig"
    assert pig_phrase_speed == 1.0
    assert tts_voice("one small pig") == ("bf_alice", "en-gb")
    assert tts_render("the green frog") == ("the green frog", 1.0)
    assert tts_voice("the green frog") == ("bf_alice", "en-gb")
    assert tts_render("frog") == ("frog.", 0.95)

    long_line, long_line_speed = tts_render("Jack and Jill went up the hill")
    assert long_line == "Jack and Jill went up the hill..."
    assert long_line_speed == 0.95
    assert tts_voice("Jack and Jill went up the hill") == ("bf_emma", "en-gb")
    # Short phrases stay bare (ellipsis smears ducks/pig).
    assert tts_render("two wet ducks") == ("two wet ducks", 0.95)
    assert tts_render("Rain rain go away") == ("rain rain go away", 0.95)


def test_hot_sun_phrase_uses_alice_so_sun_stays_sun():
    """Emma can smear final sun; Alice keeps the word."""
    for text in ("The hot sun", "A hot sun", "a hot sun"):
        spoken, speed = tts_render(text)
        assert spoken.rstrip(".!?").lower() == text.lower()
        assert speed == 0.95
        assert tts_voice(text) == ("bf_alice", "en-gb")


def test_tts_render_log_and_hard_g():
    log, log_speed = tts_render("log")
    assert log == "log."
    assert log_speed == 0.95
    assert tts_voice("log") == ("bf_alice", "en-gb")
    net, net_speed = tts_render("net")
    assert net == "net."
    assert net_speed == 0.95
    assert tts_voice("net") == (None, None)


def test_tts_render_avoids_a_period_burst():
    a, a_speed = tts_render("a")
    assert a == "a"
    assert not a.endswith(".")
    assert a_speed >= 0.92
    bring, bring_speed = tts_render("bring")
    assert bring == "bring."
    assert spoken_matches_target("bring", bring)
    assert bring_speed >= 0.94


def test_tts_render_ng_is_not_treated_as_plosive_g():
    bring, bring_speed = tts_render("bring")
    assert bring == "bring."
    assert bring_speed >= 0.94
    long, long_speed = tts_render("long")
    assert long == "long."
    assert long_speed >= 0.94
    assert tts_render("frog") == ("frog.", 0.95)
    assert tts_render("dog") == ("dog.", 0.95)


def test_tts_render_sit_and_top_allowlist():
    spoken, speed = tts_render("sit")
    assert spoken == "sit."
    assert speed == 0.95
    assert tts_voice("sit") == ("bf_alice", "en-gb")
    voice, lang = tts_voice("top")
    assert voice == "bm_lewis"
    assert lang == "en-gb"
    spoken_top, speed_top = tts_render("top")
    assert spoken_top == "top."
    assert speed_top == 0.95


def test_tts_render_shell_stays_single_word():
    spoken, speed = tts_render("shell")
    assert spoken_matches_target("shell", spoken)
    assert speed >= 0.92


def test_tts_render_cat_is_only_cat():
    spoken, speed = tts_render("cat")
    assert spoken == "cat."
    assert spoken_matches_target("cat", spoken)
    assert speed == 0.95
    assert tts_voice("cat") == (None, None)  # default Emma


def test_phrase_defaults_and_rain():
    assert tts_voice("two wet ducks") == ("bf_emma", "en-gb")
    assert tts_render("two wet ducks") == ("two wet ducks", 0.95)
    assert tts_render("one small pig") == ("one small pig", 1.0)
    assert tts_voice("one small pig") == ("bf_alice", "en-gb")
    assert tts_voice("Rain rain go away") == ("bf_emma", "en-gb")
    assert tts_render("Rain rain go away") == ("rain rain go away", 0.95)
    assert tts_voice("three red hats") == ("bf_alice", "en-gb")
    assert tts_render("three red hats") == ("three red hats", 0.95)
