#!/usr/bin/env python3
"""Fill sound_tags from a local CMU Pronouncing Dictionary (Milestone 3).

Downloads are expected at setup time into models/cmudict/cmudict.dict (or
models/cmudict-0.7b). Rows with sounds_locked=1 are never overwritten.

ARPAbet map (plan):
  TH, DH → th
  R, ER* → r
  S (not Z) → s
  SH → sh
  CH → ch
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.matching import normalize_text  # noqa: E402

CMU_URL = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"
CMU_PATHS = [
    config.MODELS_DIR / "cmudict" / "cmudict.dict",
    config.MODELS_DIR / "cmudict-0.7b",
    config.MODELS_DIR / "cmudict.dict",
]


def find_cmudict() -> Path | None:
    for path in CMU_PATHS:
        if path.exists():
            return path
    return None


def download_cmudict(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CMU dict → {dest}")
    urllib.request.urlretrieve(CMU_URL, dest)
    return dest


def load_cmu(path: Path) -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";;;"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            word = parts[0].lower()
            word = re.sub(r"\(\d+\)$", "", word)
            phones = parts[1:]
            table.setdefault(word, phones)
    return table


def phones_to_tags(phones: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for p in phones:
        base = re.sub(r"\d", "", p).upper()
        tag = None
        if base in ("TH", "DH"):
            tag = "th"
        elif base == "R" or base.startswith("ER"):
            tag = "r"
        elif base == "S":
            tag = "s"
        elif base == "SH":
            tag = "sh"
        elif base == "CH":
            tag = "ch"
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def words_in(text: str) -> list[str]:
    return normalize_text(text).split()


def main() -> int:
    parser = argparse.ArgumentParser(description="Tag item sound_tags from CMU dict")
    parser.add_argument("--download", action="store_true", help="Fetch CMU dict if missing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cmu_path = find_cmudict()
    if cmu_path is None:
        if args.download:
            cmu_path = download_cmudict(CMU_PATHS[0])
        else:
            print("CMU dict not found. Re-run with --download.", file=sys.stderr)
            return 1

    cmu = load_cmu(cmu_path)
    with config.CONTENT_ITEMS.open(encoding="utf-8") as f:
        items = json.load(f)

    updated = 0
    missing = 0
    for item in items:
        if item.get("sounds_locked"):
            continue
        tags: list[str] = []
        seen: set[str] = set()
        any_hit = False
        for word in words_in(item["text"]):
            phones = cmu.get(word)
            if not phones:
                missing += 1
                continue
            any_hit = True
            for tag in phones_to_tags(phones):
                if tag not in seen:
                    tags.append(tag)
                    seen.add(tag)
        if not any_hit:
            continue
        if item.get("sound_tags") != tags:
            item["sound_tags"] = tags
            updated += 1

    print(f"Updated {updated} items; {missing} word tokens missing from CMU (skipped those tokens)")
    if not args.dry_run:
        with config.CONTENT_ITEMS.open("w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
            f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
