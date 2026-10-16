#!/usr/bin/env python3
"""Generate simple colorful SVG pictograms for Reading Buddy words.

These are original geometric drawings (not stock memes) sized for the stage.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "illustrations"

# word → list of SVG shape snippets inside a 120x120 viewBox
DRAWINGS: dict[str, str] = {
    "cat": """
      <ellipse cx="60" cy="72" rx="34" ry="28" fill="#f4c27a"/>
      <circle cx="42" cy="48" r="16" fill="#f4c27a"/>
      <circle cx="78" cy="48" r="16" fill="#f4c27a"/>
      <polygon points="30,40 36,18 48,38" fill="#e09b45"/>
      <polygon points="90,40 84,18 72,38" fill="#e09b45"/>
      <circle cx="54" cy="50" r="3" fill="#2c241c"/>
      <circle cx="66" cy="50" r="3" fill="#2c241c"/>
      <ellipse cx="60" cy="58" rx="4" ry="3" fill="#ff8f6b"/>
    """,
    "dog": """
      <ellipse cx="62" cy="70" rx="36" ry="26" fill="#d4a574"/>
      <ellipse cx="40" cy="48" rx="18" ry="16" fill="#d4a574"/>
      <ellipse cx="28" cy="52" rx="8" ry="14" fill="#b8895a"/>
      <ellipse cx="48" cy="52" rx="8" ry="14" fill="#b8895a"/>
      <circle cx="36" cy="46" r="3" fill="#2c241c"/>
      <ellipse cx="34" cy="54" rx="4" ry="3" fill="#ff8f6b"/>
      <path d="M78 68 Q100 50 108 78" stroke="#d4a574" stroke-width="8" fill="none" stroke-linecap="round"/>
    """,
    "sun": """
      <circle cx="60" cy="60" r="28" fill="#ffd56a"/>
      <g stroke="#ffb020" stroke-width="6" stroke-linecap="round">
        <line x1="60" y1="12" x2="60" y2="26"/><line x1="60" y1="94" x2="60" y2="108"/>
        <line x1="12" y1="60" x2="26" y2="60"/><line x1="94" y1="60" x2="108" y2="60"/>
        <line x1="26" y1="26" x2="36" y2="36"/><line x1="84" y1="84" x2="94" y2="94"/>
        <line x1="94" y1="26" x2="84" y2="36"/><line x1="36" y1="84" x2="26" y2="94"/>
      </g>
    """,
    "pen": """
      <rect x="52" y="18" width="16" height="70" rx="4" fill="#3aa0d0" transform="rotate(20 60 60)"/>
      <polygon points="78,92 88,102 70,98" fill="#2c241c"/>
      <rect x="48" y="14" width="16" height="14" rx="3" fill="#ff8f6b" transform="rotate(20 60 60)"/>
    """,
    "hat": """
      <ellipse cx="60" cy="78" rx="42" ry="12" fill="#7bc47f"/>
      <path d="M35 78 Q35 40 60 36 Q85 40 85 78 Z" fill="#3f9a5f"/>
      <rect x="34" y="70" width="52" height="8" rx="3" fill="#ffd56a"/>
    """,
    "bed": """
      <rect x="18" y="58" width="84" height="28" rx="6" fill="#7ec8e8"/>
      <rect x="22" y="42" width="36" height="22" rx="6" fill="#fff6e8"/>
      <rect x="18" y="80" width="8" height="18" fill="#5c4f42"/>
      <rect x="94" y="80" width="8" height="18" fill="#5c4f42"/>
      <circle cx="70" cy="52" r="10" fill="#ffb0c8"/>
    """,
    "pig": """
      <ellipse cx="60" cy="68" rx="36" ry="28" fill="#ffb0c8"/>
      <circle cx="38" cy="48" r="14" fill="#ffb0c8"/>
      <circle cx="82" cy="48" r="14" fill="#ffb0c8"/>
      <ellipse cx="60" cy="72" rx="12" ry="9" fill="#ff8f6b"/>
      <circle cx="55" cy="72" r="2" fill="#2c241c"/>
      <circle cx="65" cy="72" r="2" fill="#2c241c"/>
      <circle cx="50" cy="58" r="3" fill="#2c241c"/>
      <circle cx="70" cy="58" r="3" fill="#2c241c"/>
    """,
    "cup": """
      <path d="M34 36 h44 v40 c0 16 -44 16 -44 0 Z" fill="#7ec8e8"/>
      <path d="M78 44 h14 c8 0 8 24 0 24 h-14" fill="none" stroke="#3aa0d0" stroke-width="7"/>
      <ellipse cx="56" cy="36" rx="22" ry="7" fill="#cfeeff"/>
      <rect x="40" y="48" width="28" height="6" rx="2" fill="#fff"/>
    """,
    "map": """
      <path d="M20 30 L48 24 L72 34 L100 26 L100 90 L72 98 L48 88 L20 96 Z" fill="#e8f7ea" stroke="#3f9a5f" stroke-width="3"/>
      <path d="M48 24 V88 M72 34 V98" stroke="#a8d5c5" stroke-width="2"/>
      <circle cx="58" cy="56" r="5" fill="#ff8f6b"/>
      <path d="M58 61 L58 74" stroke="#ff8f6b" stroke-width="3"/>
    """,
    "bus": """
      <rect x="16" y="40" width="88" height="42" rx="10" fill="#ffb020"/>
      <rect x="24" y="48" width="20" height="16" rx="3" fill="#cfeeff"/>
      <rect x="50" y="48" width="20" height="16" rx="3" fill="#cfeeff"/>
      <rect x="76" y="48" width="18" height="16" rx="3" fill="#cfeeff"/>
      <circle cx="36" cy="86" r="9" fill="#2c241c"/>
      <circle cx="86" cy="86" r="9" fill="#2c241c"/>
      <circle cx="36" cy="86" r="4" fill="#bbb"/>
      <circle cx="86" cy="86" r="4" fill="#bbb"/>
    """,
    "fox": """
      <ellipse cx="60" cy="74" rx="30" ry="22" fill="#ff8f6b"/>
      <polygon points="60,30 36,70 84,70" fill="#ff8f6b"/>
      <polygon points="32,42 28,20 48,40" fill="#ff8f6b"/>
      <polygon points="88,42 92,20 72,40" fill="#ff8f6b"/>
      <polygon points="60,58 52,70 68,70" fill="#fff6e8"/>
      <circle cx="50" cy="58" r="3" fill="#2c241c"/>
      <circle cx="70" cy="58" r="3" fill="#2c241c"/>
    """,
    "jam": """
      <rect x="38" y="40" width="44" height="52" rx="8" fill="#e74c6f"/>
      <rect x="42" y="28" width="36" height="16" rx="4" fill="#fff6e8"/>
      <rect x="46" y="20" width="28" height="12" rx="3" fill="#7ec8e8"/>
      <circle cx="56" cy="62" r="4" fill="#ffd56a"/>
      <circle cx="68" cy="72" r="3" fill="#ffd56a"/>
    """,
    "kid": """
      <circle cx="60" cy="40" r="18" fill="#f4c27a"/>
      <path d="M40 62 Q60 52 80 62 L84 100 L36 100 Z" fill="#7ec8e8"/>
      <circle cx="53" cy="38" r="2.5" fill="#2c241c"/>
      <circle cx="67" cy="38" r="2.5" fill="#2c241c"/>
      <path d="M54 46 Q60 50 66 46" stroke="#2c241c" stroke-width="2" fill="none"/>
    """,
    "log": """
      <ellipse cx="60" cy="60" rx="48" ry="22" fill="#b8895a"/>
      <ellipse cx="100" cy="60" rx="10" ry="22" fill="#d4a574"/>
      <ellipse cx="100" cy="60" rx="5" ry="12" fill="#8b5e34"/>
      <path d="M30 55 Q50 48 70 58" stroke="#8b5e34" stroke-width="3" fill="none"/>
    """,
    "net": """
      <path d="M24 28 L96 28 L84 96 L36 96 Z" fill="none" stroke="#3aa0d0" stroke-width="5"/>
      <path d="M36 28 V96 M48 28 V96 M60 28 V96 M72 28 V96 M84 28 V96" stroke="#7ec8e8" stroke-width="2"/>
      <path d="M24 44 H92 M28 60 H88 M32 76 H84" stroke="#7ec8e8" stroke-width="2"/>
    """,
    "rat": """
      <ellipse cx="58" cy="68" rx="32" ry="20" fill="#b0b7c3"/>
      <circle cx="40" cy="52" r="14" fill="#b0b7c3"/>
      <circle cx="32" cy="42" r="7" fill="#cfd5de"/>
      <circle cx="44" cy="40" r="7" fill="#cfd5de"/>
      <circle cx="36" cy="52" r="2.5" fill="#2c241c"/>
      <path d="M88 68 Q108 50 112 80" stroke="#b0b7c3" stroke-width="6" fill="none" stroke-linecap="round"/>
    """,
    "sit": """
      <rect x="30" y="48" width="60" height="12" rx="4" fill="#8b5e34"/>
      <rect x="34" y="60" width="10" height="34" fill="#8b5e34"/>
      <rect x="76" y="60" width="10" height="34" fill="#8b5e34"/>
      <rect x="78" y="20" width="12" height="40" fill="#8b5e34"/>
      <circle cx="50" cy="36" r="12" fill="#f4c27a"/>
    """,
    "top": """
      <ellipse cx="60" cy="78" rx="28" ry="10" fill="#ff8f6b"/>
      <path d="M40 78 L60 22 L80 78 Z" fill="#ffb020"/>
      <circle cx="60" cy="18" r="6" fill="#7ec8e8"/>
      <ellipse cx="60" cy="55" rx="10" ry="4" fill="#fff6e8" opacity="0.7"/>
    """,
    "van": """
      <rect x="14" y="48" width="70" height="36" rx="8" fill="#7bc47f"/>
      <path d="M84 56 h16 l8 16 v12 h-24 Z" fill="#3f9a5f"/>
      <rect x="90" y="60" width="12" height="12" rx="2" fill="#cfeeff"/>
      <circle cx="36" cy="90" r="9" fill="#2c241c"/>
      <circle cx="86" cy="90" r="9" fill="#2c241c"/>
    """,
    "wet": """
      <path d="M40 28 Q30 60 40 90 Q60 100 80 90 Q90 60 80 28 Q60 18 40 28 Z" fill="#7ec8e8"/>
      <path d="M50 40 Q46 60 52 78" stroke="#fff" stroke-width="4" fill="none" opacity="0.7"/>
      <circle cx="70" cy="56" r="4" fill="#fff" opacity="0.8"/>
    """,
    "ship": """
      <path d="M20 70 L100 70 L88 92 L32 92 Z" fill="#8b5e34"/>
      <path d="M60 70 L60 28" stroke="#5c4f42" stroke-width="4"/>
      <path d="M64 32 L96 68 L64 68 Z" fill="#fff6e8"/>
      <path d="M56 40 L28 68 L56 68 Z" fill="#7ec8e8"/>
      <path d="M16 96 Q60 108 104 96" stroke="#3aa0d0" stroke-width="4" fill="none"/>
    """,
    "frog": """
      <ellipse cx="60" cy="70" rx="34" ry="24" fill="#7bc47f"/>
      <circle cx="40" cy="48" r="14" fill="#7bc47f"/>
      <circle cx="80" cy="48" r="14" fill="#7bc47f"/>
      <circle cx="40" cy="48" r="6" fill="#fff"/>
      <circle cx="80" cy="48" r="6" fill="#fff"/>
      <circle cx="40" cy="48" r="3" fill="#2c241c"/>
      <circle cx="80" cy="48" r="3" fill="#2c241c"/>
      <ellipse cx="60" cy="78" rx="10" ry="6" fill="#3f9a5f"/>
    """,
    "book": """
      <path d="M24 28 L58 34 L58 96 L24 90 Z" fill="#3aa0d0"/>
      <path d="M96 28 L62 34 L62 96 L96 90 Z" fill="#ff8f6b"/>
      <path d="M58 34 L62 34 L62 96 L58 96 Z" fill="#fff6e8"/>
      <path d="M32 48 H50 M32 60 H50" stroke="#fff" stroke-width="3"/>
    """,
    "star": """
      <polygon points="60,14 70,46 104,46 76,66 86,98 60,78 34,98 44,66 16,46 50,46"
        fill="#ffd56a" stroke="#ffb020" stroke-width="3" stroke-linejoin="round"/>
    """,
    "moon": """
      <circle cx="60" cy="60" r="34" fill="#ffd56a"/>
      <circle cx="74" cy="50" r="28" fill="#e7f6ff"/>
      <circle cx="48" cy="70" r="3" fill="#e09b45" opacity="0.5"/>
      <circle cx="40" cy="48" r="2" fill="#e09b45" opacity="0.4"/>
    """,
    "tree": """
      <rect x="52" y="70" width="16" height="30" fill="#8b5e34"/>
      <circle cx="60" cy="48" r="28" fill="#3f9a5f"/>
      <circle cx="42" cy="58" r="16" fill="#7bc47f"/>
      <circle cx="78" cy="58" r="16" fill="#7bc47f"/>
    """,
    "hill": """
      <path d="M8 96 Q40 28 60 48 Q80 20 112 96 Z" fill="#7bc47f"/>
      <path d="M50 40 Q60 28 70 40" stroke="#fff" stroke-width="4" fill="none"/>
      <circle cx="88" cy="28" r="8" fill="#ffd56a"/>
    """,
    "clock": """
      <circle cx="60" cy="62" r="36" fill="#fff6e8" stroke="#5c4f42" stroke-width="6"/>
      <circle cx="60" cy="62" r="4" fill="#5c4f42"/>
      <line x1="60" y1="62" x2="60" y2="38" stroke="#2c241c" stroke-width="4" stroke-linecap="round"/>
      <line x1="60" y1="62" x2="80" y2="70" stroke="#ff8f6b" stroke-width="3" stroke-linecap="round"/>
    """,
    "train": """
      <rect x="20" y="50" width="50" height="34" rx="6" fill="#3aa0d0"/>
      <rect x="70" y="58" width="34" height="26" rx="4" fill="#ff8f6b"/>
      <rect x="28" y="58" width="14" height="12" fill="#cfeeff"/>
      <circle cx="36" cy="90" r="8" fill="#2c241c"/>
      <circle cx="62" cy="90" r="8" fill="#2c241c"/>
      <circle cx="88" cy="90" r="8" fill="#2c241c"/>
      <rect x="78" y="40" width="10" height="18" fill="#5c4f42"/>
    """,
    "sheep": """
      <ellipse cx="62" cy="68" rx="34" ry="24" fill="#fff6e8" stroke="#d4c4a8" stroke-width="3"/>
      <circle cx="36" cy="60" r="14" fill="#2c241c"/>
      <circle cx="30" cy="56" r="3" fill="#fff"/>
      <circle cx="70" cy="52" r="10" fill="#fff6e8" stroke="#d4c4a8" stroke-width="2"/>
      <circle cx="88" cy="64" r="10" fill="#fff6e8" stroke="#d4c4a8" stroke-width="2"/>
    """,
    "fish": """
      <ellipse cx="58" cy="60" rx="32" ry="20" fill="#3aa0d0"/>
      <polygon points="88,60 108,40 108,80" fill="#7ec8e8"/>
      <circle cx="42" cy="56" r="4" fill="#fff"/>
      <circle cx="42" cy="56" r="2" fill="#2c241c"/>
    """,
    "bird": """
      <ellipse cx="60" cy="64" rx="28" ry="20" fill="#7ec8e8"/>
      <circle cx="78" cy="48" r="14" fill="#7ec8e8"/>
      <polygon points="90,48 108,52 90,58" fill="#ffb020"/>
      <circle cx="82" cy="46" r="2.5" fill="#2c241c"/>
      <path d="M40 64 Q28 48 44 52" fill="#3aa0d0"/>
    """,
    "cake": """
      <rect x="28" y="56" width="64" height="28" rx="6" fill="#f4c27a"/>
      <rect x="28" y="40" width="64" height="20" rx="6" fill="#ffb0c8"/>
      <rect x="54" y="22" width="12" height="20" fill="#ffd56a"/>
      <circle cx="60" cy="20" r="6" fill="#ff8f6b"/>
      <circle cx="40" cy="50" r="3" fill="#fff"/>
      <circle cx="70" cy="48" r="3" fill="#fff"/>
    """,
    "bike": """
      <circle cx="34" cy="78" r="18" fill="none" stroke="#2c241c" stroke-width="5"/>
      <circle cx="90" cy="78" r="18" fill="none" stroke="#2c241c" stroke-width="5"/>
      <path d="M34 78 L58 48 L78 78 L58 48 L70 36" stroke="#3aa0d0" stroke-width="5" fill="none" stroke-linecap="round"/>
      <circle cx="58" cy="48" r="4" fill="#ff8f6b"/>
    """,
    "flag": """
      <rect x="30" y="18" width="8" height="88" fill="#8b5e34"/>
      <path d="M38 22 H96 L84 42 L96 62 H38 Z" fill="#ff8f6b"/>
      <circle cx="58" cy="42" r="6" fill="#ffd56a"/>
    """,
    "drum": """
      <ellipse cx="60" cy="40" rx="36" ry="14" fill="#ff8f6b"/>
      <path d="M24 40 V78 Q60 96 96 78 V40" fill="#e09b45"/>
      <ellipse cx="60" cy="78" rx="36" ry="14" fill="#c47a30"/>
      <line x1="36" y1="44" x2="36" y2="76" stroke="#fff6e8" stroke-width="3"/>
      <line x1="84" y1="44" x2="84" y2="76" stroke="#fff6e8" stroke-width="3"/>
    """,
    "chair": """
      <rect x="34" y="40" width="52" height="12" rx="3" fill="#8b5e34"/>
      <rect x="34" y="20" width="12" height="70" fill="#8b5e34"/>
      <rect x="74" y="52" width="12" height="38" fill="#8b5e34"/>
      <rect x="34" y="52" width="12" height="38" fill="#8b5e34"/>
      <rect x="38" y="52" width="44" height="8" fill="#d4a574"/>
    """,
    "truck": """
      <rect x="12" y="50" width="58" height="32" rx="4" fill="#ffb020"/>
      <rect x="70" y="58" width="36" height="24" rx="4" fill="#3aa0d0"/>
      <rect x="78" y="64" width="14" height="10" fill="#cfeeff"/>
      <circle cx="32" cy="88" r="9" fill="#2c241c"/>
      <circle cx="86" cy="88" r="9" fill="#2c241c"/>
    """,
    "spoon": """
      <ellipse cx="40" cy="36" rx="16" ry="20" fill="#c0c6ce"/>
      <rect x="34" y="52" width="12" height="52" rx="5" fill="#a8aeb8"/>
      <ellipse cx="40" cy="36" rx="10" ry="13" fill="#e8ebf0"/>
    """,
    "grass": """
      <path d="M20 96 Q30 40 40 96" fill="#3f9a5f"/>
      <path d="M40 96 Q52 28 64 96" fill="#7bc47f"/>
      <path d="M58 96 Q72 36 84 96" fill="#3f9a5f"/>
      <path d="M78 96 Q92 44 104 96" fill="#7bc47f"/>
      <ellipse cx="60" cy="100" rx="50" ry="8" fill="#a8d5c5"/>
    """,
    "slide": """
      <path d="M28 24 L88 24 L88 36 L40 36 L92 96 L76 96 L28 40 Z" fill="#3aa0d0"/>
      <rect x="24" y="20" width="68" height="10" rx="3" fill="#ffb020"/>
      <circle cx="70" cy="70" r="8" fill="#f4c27a"/>
    """,
    "trap": """
      <rect x="28" y="48" width="64" height="40" rx="6" fill="#8b5e34"/>
      <path d="M28 48 L60 24 L92 48" fill="#b8895a"/>
      <circle cx="60" cy="64" r="8" fill="#ffd56a"/>
    """,
    "brush": """
      <rect x="50" y="18" width="20" height="50" rx="6" fill="#8b5e34"/>
      <rect x="42" y="64" width="36" height="36" rx="8" fill="#7ec8e8"/>
      <path d="M48 72 V92 M56 70 V94 M64 70 V94 M72 72 V92" stroke="#3aa0d0" stroke-width="3"/>
    """,
    "flash": """
      <polygon points="64,12 40,64 56,64 48,108 88,48 68,48" fill="#ffd56a" stroke="#ffb020" stroke-width="3" stroke-linejoin="round"/>
    """,
    "swim": """
      <ellipse cx="60" cy="58" rx="26" ry="14" fill="#f4c27a"/>
      <circle cx="82" cy="50" r="10" fill="#f4c27a"/>
      <path d="M16 78 Q40 68 60 78 Q80 88 104 78" stroke="#3aa0d0" stroke-width="5" fill="none"/>
      <path d="M20 90 Q44 80 64 90 Q84 100 100 90" stroke="#7ec8e8" stroke-width="4" fill="none"/>
    """,
    "chop": """
      <rect x="30" y="50" width="60" height="18" rx="4" fill="#d4a574"/>
      <path d="M70 30 L100 55 L70 50 Z" fill="#a8aeb8"/>
      <rect x="58" y="48" width="14" height="8" fill="#5c4f42"/>
    """,
    "thin": """
      <rect x="54" y="20" width="12" height="80" rx="6" fill="#7ec8e8"/>
      <rect x="30" y="30" width="60" height="10" rx="4" fill="#3aa0d0"/>
      <text x="60" y="70" text-anchor="middle" font-size="20" fill="#fff" font-family="Trebuchet MS,sans-serif">1</text>
    """,
    "three": """
      <circle cx="34" cy="60" r="16" fill="#ff8f6b"/>
      <circle cx="60" cy="40" r="16" fill="#ffd56a"/>
      <circle cx="86" cy="60" r="16" fill="#7ec8e8"/>
      <text x="34" y="66" text-anchor="middle" font-size="16" fill="#fff" font-weight="700">1</text>
      <text x="60" y="46" text-anchor="middle" font-size="16" fill="#5c4f42" font-weight="700">2</text>
      <text x="86" y="66" text-anchor="middle" font-size="16" fill="#fff" font-weight="700">3</text>
    """,
    "red": """
      <circle cx="60" cy="60" r="36" fill="#e74c6f"/>
      <circle cx="60" cy="60" r="20" fill="#ff8f6b"/>
    """,
    "blue": """
      <circle cx="60" cy="60" r="36" fill="#3aa0d0"/>
      <circle cx="60" cy="60" r="20" fill="#7ec8e8"/>
    """,
    "green": """
      <circle cx="60" cy="60" r="36" fill="#3f9a5f"/>
      <circle cx="60" cy="60" r="20" fill="#7bc47f"/>
    """,
    "hot": """
      <path d="M44 96 Q36 50 48 28 Q60 50 60 96 Z" fill="#ff8f6b"/>
      <path d="M60 96 Q60 40 72 24 Q84 48 76 96 Z" fill="#ffb020"/>
      <path d="M50 96 Q52 60 60 44 Q68 60 70 96 Z" fill="#ffd56a"/>
    """,
    "cold": """
      <g stroke="#3aa0d0" stroke-width="5" stroke-linecap="round">
        <line x1="60" y1="20" x2="60" y2="100"/>
        <line x1="28" y1="36" x2="92" y2="84"/>
        <line x1="92" y1="36" x2="28" y2="84"/>
      </g>
      <circle cx="60" cy="60" r="8" fill="#cfeeff" stroke="#3aa0d0" stroke-width="3"/>
    """,
    "water": """
      <path d="M20 50 Q40 40 60 50 Q80 60 100 50" stroke="#3aa0d0" stroke-width="6" fill="none"/>
      <path d="M20 70 Q40 60 60 70 Q80 80 100 70" stroke="#7ec8e8" stroke-width="6" fill="none"/>
      <path d="M20 90 Q40 80 60 90 Q80 100 100 90" stroke="#3aa0d0" stroke-width="6" fill="none"/>
    """,
    "milk": """
      <path d="M40 30 h40 l8 70 h-56 Z" fill="#fff6e8" stroke="#d4c4a8" stroke-width="3"/>
      <rect x="44" y="20" width="32" height="14" rx="3" fill="#7ec8e8"/>
      <path d="M48 55 H72" stroke="#e8ebf0" stroke-width="8"/>
    """,
    "bag": """
      <path d="M34 44 h52 l6 52 h-64 Z" fill="#d4a574"/>
      <path d="M46 44 Q60 28 74 44" stroke="#8b5e34" stroke-width="6" fill="none"/>
      <circle cx="60" cy="70" r="6" fill="#ffd56a"/>
    """,
    "park": """
      <ellipse cx="60" cy="88" rx="48" ry="14" fill="#7bc47f"/>
      <rect x="54" y="50" width="12" height="40" fill="#8b5e34"/>
      <circle cx="60" cy="42" r="22" fill="#3f9a5f"/>
      <circle cx="30" cy="70" r="8" fill="#ffd56a"/>
    """,
    "mat": """
      <rect x="18" y="40" width="84" height="48" rx="10" fill="#e74c6f"/>
      <rect x="28" y="50" width="64" height="28" rx="6" fill="#ffb0c8"/>
      <path d="M36 64 H84" stroke="#fff" stroke-width="4" stroke-dasharray="6 6"/>
    """,
    "pond": """
      <ellipse cx="60" cy="64" rx="46" ry="28" fill="#3aa0d0"/>
      <ellipse cx="60" cy="64" rx="34" ry="18" fill="#7ec8e8"/>
      <circle cx="44" cy="60" r="4" fill="#fff" opacity="0.7"/>
      <path d="M70 40 Q78 28 90 34" stroke="#7bc47f" stroke-width="5" fill="none"/>
    """,
    "rain": """
      <ellipse cx="60" cy="40" rx="36" ry="18" fill="#b0b7c3"/>
      <g stroke="#3aa0d0" stroke-width="4" stroke-linecap="round">
        <line x1="36" y1="66" x2="30" y2="92"/>
        <line x1="54" y1="70" x2="48" y2="100"/>
        <line x1="72" y1="68" x2="68" y2="96"/>
        <line x1="88" y1="66" x2="84" y2="90"/>
      </g>
    """,
    "snow": """
      <g stroke="#7ec8e8" stroke-width="4" stroke-linecap="round">
        <line x1="40" y1="30" x2="40" y2="55"/><line x1="28" y1="42" x2="52" y2="42"/>
        <line x1="80" y1="50" x2="80" y2="78"/><line x1="66" y1="64" x2="94" y2="64"/>
        <line x1="55" y1="78" x2="55" y2="102"/><line x1="42" y1="90" x2="68" y2="90"/>
      </g>
      <circle cx="40" cy="42" r="4" fill="#cfeeff"/>
      <circle cx="80" cy="64" r="4" fill="#cfeeff"/>
    """,
    "house": """
      <rect x="30" y="52" width="60" height="44" fill="#f4c27a"/>
      <polygon points="24,52 60,22 96,52" fill="#ff8f6b"/>
      <rect x="50" y="68" width="20" height="28" fill="#8b5e34"/>
      <rect x="36" y="62" width="12" height="12" fill="#7ec8e8"/>
      <rect x="72" y="62" width="12" height="12" fill="#7ec8e8"/>
    """,
    "friend": """
      <circle cx="42" cy="44" r="14" fill="#f4c27a"/>
      <circle cx="78" cy="44" r="14" fill="#d4a574"/>
      <path d="M28 70 Q42 58 56 70 L56 96 L28 96 Z" fill="#7ec8e8"/>
      <path d="M64 70 Q78 58 92 70 L92 96 L64 96 Z" fill="#ffb0c8"/>
    """,
    "read": """
      <path d="M28 32 L56 38 L56 96 L28 90 Z" fill="#3aa0d0"/>
      <path d="M92 32 L64 38 L64 96 L92 90 Z" fill="#7bc47f"/>
      <circle cx="60" cy="28" r="12" fill="#f4c27a"/>
    """,
    "play": """
      <circle cx="60" cy="60" r="36" fill="#ffd56a"/>
      <polygon points="48,42 48,78 82,60" fill="#ff8f6b"/>
    """,
    "look": """
      <circle cx="46" cy="56" r="22" fill="none" stroke="#3aa0d0" stroke-width="8"/>
      <line x1="62" y1="72" x2="92" y2="98" stroke="#3aa0d0" stroke-width="8" stroke-linecap="round"/>
      <circle cx="46" cy="56" r="8" fill="#7ec8e8"/>
    """,
    "run": """
      <circle cx="58" cy="28" r="12" fill="#f4c27a"/>
      <path d="M50 42 L44 70 L30 96" stroke="#3aa0d0" stroke-width="7" fill="none" stroke-linecap="round"/>
      <path d="M50 42 L70 64 L90 50" stroke="#3aa0d0" stroke-width="7" fill="none" stroke-linecap="round"/>
      <path d="M44 70 L66 78 L58 100" stroke="#ff8f6b" stroke-width="7" fill="none" stroke-linecap="round"/>
    """,
    "jump": """
      <circle cx="60" cy="30" r="12" fill="#f4c27a"/>
      <path d="M60 44 L48 70 L34 64" stroke="#7bc47f" stroke-width="7" fill="none" stroke-linecap="round"/>
      <path d="M60 44 L72 70 L90 58" stroke="#7bc47f" stroke-width="7" fill="none" stroke-linecap="round"/>
      <path d="M20 96 Q60 80 100 96" stroke="#a8d5c5" stroke-width="5" fill="none"/>
    """,
    "soft": """
      <ellipse cx="60" cy="64" rx="38" ry="30" fill="#ffb0c8"/>
      <ellipse cx="60" cy="64" rx="24" ry="18" fill="#ffe0ea"/>
      <circle cx="48" cy="58" r="4" fill="#fff"/>
      <circle cx="70" cy="70" r="3" fill="#fff"/>
    """,
    "bright": """
      <circle cx="60" cy="60" r="20" fill="#ffd56a"/>
      <g stroke="#ffb020" stroke-width="5" stroke-linecap="round">
        <line x1="60" y1="18" x2="60" y2="32"/>
        <line x1="60" y1="88" x2="60" y2="102"/>
        <line x1="18" y1="60" x2="32" y2="60"/>
        <line x1="88" y1="60" x2="102" y2="60"/>
        <line x1="30" y1="30" x2="40" y2="40"/>
        <line x1="80" y1="80" x2="90" y2="90"/>
        <line x1="90" y1="30" x2="80" y2="40"/>
        <line x1="40" y1="80" x2="30" y2="90"/>
      </g>
    """,
    "old": """
      <circle cx="60" cy="50" r="22" fill="#d4a574"/>
      <path d="M40 78 Q60 68 80 78 L84 100 L36 100 Z" fill="#8b5e34"/>
      <path d="M48 46 Q52 50 56 46" stroke="#5c4f42" stroke-width="2" fill="none"/>
      <path d="M64 46 Q68 50 72 46" stroke="#5c4f42" stroke-width="2" fill="none"/>
      <circle cx="52" cy="52" r="2" fill="#2c241c"/>
      <circle cx="68" cy="52" r="2" fill="#2c241c"/>
    """,
    "big": """
      <rect x="20" y="30" width="80" height="64" rx="12" fill="#7ec8e8"/>
      <text x="60" y="72" text-anchor="middle" font-size="28" font-weight="800" fill="#1f4f63" font-family="Trebuchet MS,sans-serif">BIG</text>
    """,
    "little": """
      <rect x="42" y="48" width="36" height="30" rx="8" fill="#ffb0c8"/>
      <text x="60" y="68" text-anchor="middle" font-size="12" font-weight="800" fill="#7a2e16" font-family="Trebuchet MS,sans-serif">tiny</text>
    """,
    "fat": """
      <ellipse cx="60" cy="64" rx="40" ry="32" fill="#f4c27a"/>
      <circle cx="48" cy="58" r="3" fill="#2c241c"/>
      <circle cx="72" cy="58" r="3" fill="#2c241c"/>
    """,
    "small": """
      <circle cx="60" cy="66" r="16" fill="#7ec8e8"/>
    """,
    "tall": """
      <rect x="48" y="16" width="24" height="88" rx="8" fill="#7bc47f"/>
    """,
    "quick": """
      <polygon points="18,64 70,28 62,58 102,52 46,96 56,66" fill="#ffd56a"/>
    """,
    "mouse": """
      <ellipse cx="62" cy="70" rx="30" ry="20" fill="#cfd5de"/>
      <circle cx="42" cy="52" r="14" fill="#cfd5de"/>
      <circle cx="34" cy="40" r="8" fill="#e8ebf0"/>
      <circle cx="48" cy="38" r="8" fill="#e8ebf0"/>
      <circle cx="40" cy="52" r="2.5" fill="#2c241c"/>
      <path d="M90 70 Q110 55 112 82" stroke="#cfd5de" stroke-width="6" fill="none" stroke-linecap="round"/>
    """,
    "horn": """
      <path d="M30 80 Q40 30 90 28 Q70 50 78 88 Z" fill="#ffd56a" stroke="#e09b45" stroke-width="3"/>
      <ellipse cx="34" cy="82" rx="12" ry="10" fill="#f4c27a"/>
    """,
    "crown": """
      <path d="M24 78 L24 44 L42 62 L60 30 L78 62 L96 44 L96 78 Z" fill="#ffd56a" stroke="#e09b45" stroke-width="3"/>
      <rect x="24" y="78" width="72" height="12" rx="3" fill="#ffb020"/>
      <circle cx="42" cy="58" r="4" fill="#e74c6f"/>
      <circle cx="60" cy="48" r="4" fill="#7ec8e8"/>
      <circle cx="78" cy="58" r="4" fill="#7bc47f"/>
    """,
    "wall": """
      <rect x="20" y="28" width="80" height="68" fill="#d4c4a8"/>
      <g stroke="#b8895a" stroke-width="3">
        <line x1="20" y1="50" x2="100" y2="50"/>
        <line x1="20" y1="72" x2="100" y2="72"/>
        <line x1="46" y1="28" x2="46" y2="50"/>
        <line x1="74" y1="50" x2="74" y2="72"/>
        <line x1="46" y1="72" x2="46" y2="96"/>
      </g>
    """,
}

# Aliases → canonical drawing key
ALIASES: dict[str, str] = {
    "hats": "hat",
    "bags": "bag",
    "books": "book",
    "stars": "star",
    "trees": "tree",
    "birds": "bird",
    "frogs": "frog",
    "dogs": "dog",
    "cats": "cat",
    "pigs": "pig",
    "ships": "ship",
    "trains": "train",
    "trucks": "truck",
    "sheep": "sheep",
    "lamb": "sheep",
    "ducks": "bird",
    "duck": "bird",
    "cow": "horn",
    "horses": "horn",
    "horse": "horn",
    "kings": "crown",
    "king": "crown",
    "queen": "crown",
    "master": "old",
    "dame": "old",
    "boy": "kid",
    "jill": "kid",
    "jack": "kid",
    "mary": "kid",
    "humpty": "egg",
    "dumpty": "egg",
    "twinkle": "star",
    "baa": "sheep",
    "meadow": "grass",
    "lane": "park",
    "world": "sun",
    "sky": "sun",
    "sea": "ship",
    "station": "train",
    "chalk": "pen",
    "blocks": "cake",
    "night": "moon",
    "day": "sun",
    "pail": "cup",
    "drink": "milk",
    "fetch": "dog",
    "sails": "ship",
    "sings": "bird",
    "jumps": "jump",
    "stops": "train",
    "drew": "pen",
    "fix": "bike",
    "reading": "read",
    "friend": "friend",
    "help": "friend",
    # Sets 6–8 content coverage
    "mop": "brush",
    "tap": "cup",
    "bin": "bag",
    "mud": "wet",
    "hop": "jump",
    "box": "bag",
    "win": "star",
    "leg": "kid",
    "bug": "frog",
    "bugs": "frog",
    "path": "park",
    "shop": "house",
    "clap": "play",
    "plan": "map",
    "stop": "bus",
    "drop": "water",
    "stream": "water",
    "boat": "ship",
    "row": "ship",
    "spider": "frog",
    "itsy": "frog",
    "bitsy": "frog",
    "spout": "water",
    "climbed": "hill",
    "pocket": "bag",
    "roses": "grass",
    "posies": "grass",
    "ring": "clock",
    "dream": "moon",
    "life": "sun",
    "gently": "soft",
    "merrily": "play",
    "diddle": "speech",
    "hey": "speech",
    "curds": "milk",
    "whey": "milk",
    "eating": "cake",
    "bring": "bag",
    "come": "kid",
    "said": "speech",
    "some": "soft",
    "there": "park",
    "make": "cake",
    "like": "soft",
    "long": "train",
    "dock": "ship",
    "hickory": "tree",
    "dickory": "mouse",
    "down": "hill",
    "again": "sparkle",
    "best": "star",
    "fast": "train",
    "ran": "run",
}


def egg_svg() -> str:
    return """
      <ellipse cx="60" cy="64" rx="28" ry="36" fill="#fff6e8" stroke="#d4c4a8" stroke-width="3"/>
      <path d="M40 60 Q60 48 80 60" stroke="#7ec8e8" stroke-width="4" fill="none"/>
      <path d="M42 74 Q60 86 78 74" stroke="#ffb0c8" stroke-width="4" fill="none"/>
      <circle cx="52" cy="56" r="3" fill="#ffd56a"/>
    """


FALLBACKS = {
    "egg": egg_svg(),
    "speech": """
      <ellipse cx="60" cy="50" rx="40" ry="28" fill="#fff6e8" stroke="#7ec8e8" stroke-width="4"/>
      <polygon points="44,74 52,74 40,92" fill="#fff6e8" stroke="#7ec8e8" stroke-width="4"/>
      <circle cx="46" cy="50" r="4" fill="#3aa0d0"/>
      <circle cx="60" cy="50" r="4" fill="#3aa0d0"/>
      <circle cx="74" cy="50" r="4" fill="#3aa0d0"/>
    """,
    "sparkle": """
      <polygon points="60,20 66,50 96,50 72,68 80,98 60,80 40,98 48,68 24,50 54,50" fill="#ffd56a"/>
      <circle cx="28" cy="28" r="5" fill="#7ec8e8"/>
      <circle cx="96" cy="84" r="6" fill="#ffb0c8"/>
    """,
}


def wrap(inner: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img" aria-hidden="true">
  <rect width="120" height="120" rx="28" fill="#fffaf2"/>
  {inner}
</svg>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    drawings = dict(DRAWINGS)
    drawings["egg"] = FALLBACKS["egg"]
    drawings["speech"] = FALLBACKS["speech"]
    drawings["sparkle"] = FALLBACKS["sparkle"]

    written = 0
    for key, inner in drawings.items():
        if not inner.strip():
            continue
        path = OUT / f"{key}.svg"
        path.write_text(wrap(inner), encoding="utf-8")
        written += 1

    # Alias files as copies so /static/illustrations/{word}.svg works directly
    for alias, target in ALIASES.items():
        inner = drawings.get(target)
        if not inner:
            continue
        (OUT / f"{alias}.svg").write_text(wrap(inner), encoding="utf-8")
        written += 1

    # Always write a default fallback
    (OUT / "_default.svg").write_text(wrap(FALLBACKS["sparkle"]), encoding="utf-8")
    (OUT / "_line.svg").write_text(wrap(FALLBACKS["speech"]), encoding="utf-8")

    keys = sorted(
        p.stem
        for p in OUT.glob("*.svg")
        if p.stem and not p.stem.startswith("_")
    )
    (OUT / "keys.json").write_text(
        json.dumps({"keys": keys}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {written} illustration files (+ keys.json) to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
