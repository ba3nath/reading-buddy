"""Word/line pictogram presence and stage wiring (no browser)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "game.js").read_text(encoding="utf-8")
ILLUSTRATIONS = ROOT / "static" / "illustrations"
SCRIPT = (ROOT / "scripts" / "generate_illustrations.py").read_text(encoding="utf-8")


def test_illustration_assets_exist():
    assert ILLUSTRATIONS.is_dir()
    keys_path = ILLUSTRATIONS / "keys.json"
    assert keys_path.is_file()
    data = json.loads(keys_path.read_text(encoding="utf-8"))
    keys = data["keys"]
    assert len(keys) >= 80
    for name in ("cat", "dog", "sun", "cup", "map", "star", "hill", "wall", "sheep"):
        assert name in keys
        assert (ILLUSTRATIONS / f"{name}.svg").is_file()
    assert (ILLUSTRATIONS / "_default.svg").is_file()
    assert (ILLUSTRATIONS / "_line.svg").is_file()
    cat = (ILLUSTRATIONS / "cat.svg").read_text(encoding="utf-8")
    assert 'xmlns="http://www.w3.org/2000/svg"' in cat
    assert "viewBox=" in cat


def test_stage_shows_word_art():
    assert 'data-word-art' in HTML
    assert 'data-word-art-img' in HTML
    assert "word-art" in CSS
    assert "word-art-pop" in CSS
    assert "word-art-float" in CSS
    assert "resolveIllustrationKey" in JS
    assert "setWordArt" in JS
    assert "loadIllustrationKeys" in JS
    assert "/static/illustrations/" in JS
    assert "ILLUSTRATION_STOPWORDS" in JS


def test_generator_is_original_pictograms_not_memes():
    assert "meme" not in SCRIPT.lower() or "not stock memes" in SCRIPT
    assert "DRAWINGS" in SCRIPT
    assert "ALIASES" in SCRIPT
    assert "keys.json" in SCRIPT


def test_curriculum_has_broad_illustration_coverage():
    keys = set(json.loads((ILLUSTRATIONS / "keys.json").read_text(encoding="utf-8"))["keys"])
    items = json.loads((ROOT / "content" / "items.json").read_text(encoding="utf-8"))
    stop = {
        "a", "an", "the", "and", "or", "to", "of", "on", "in", "is", "it", "at",
        "for", "as", "by", "be", "we", "he", "she", "they", "was", "were", "had",
        "has", "have", "you", "your", "my", "me", "i", "am", "are", "do", "did",
        "not", "no", "yes", "sir", "up", "any", "what", "how", "with", "from",
        "that", "this", "but", "so", "if", "then", "when", "all", "can", "will",
        "would", "could", "into", "out", "over", "under", "his", "her", "him",
        "them", "our", "us", "their", "went", "sat", "great", "full", "black",
        "wonder",
    }
    hits = 0
    for item in items:
        cleaned = "".join(c if c.isalpha() or c.isspace() else " " for c in item["text"].lower())
        tokens = [t for t in cleaned.split() if t]
        if len(tokens) == 1:
            ok = tokens[0] in keys
        else:
            ok = any(t in keys and t not in stop for t in tokens)
        if ok:
            hits += 1
    # Most of the curated list should get a real pictogram (fallback covers the rest).
    assert hits / max(len(items), 1) >= 0.7
