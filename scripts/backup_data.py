#!/usr/bin/env python3
"""One-command backup / restore of progress + parent voice overrides."""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

KEEP_NAMES = ("reading.db", "settings.json", "runner_audio_stamp.json", "runner_deps_stamp.json")


def backup(dest: Path | None = None) -> Path:
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = dest or (config.DATA_DIR / f"backup-{stamp}.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in KEEP_NAMES:
            path = config.DATA_DIR / name
            if path.is_file():
                zf.write(path, arcname=name)
        kept = config.KEPT_DIR
        if kept.is_dir():
            for wav in sorted(kept.glob("*.wav")):
                zf.write(wav, arcname=f"kept/{wav.name}")
        # Parent voice overrides (human listen clips).
        human = config.AUDIO_HUMAN
        if human.is_dir():
            for wav in sorted(human.glob("*.wav")):
                zf.write(wav, arcname=f"human/{wav.name}")
        zf.writestr(
            "BACKUP.txt",
            (
                f"Reading Buddy backup {stamp}\n"
                "Includes: data/ DB+settings, data/kept/, audio/human/.\n"
                f"Restore with: python scripts/backup_data.py restore {out.name}\n"
            ),
        )
    print(f"Wrote {out}")
    return out


def restore(src: Path, *, force: bool = False) -> None:
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)
    config.ensure_dirs()
    if not force:
        db = config.DB_PATH
        if db.is_file() and db.stat().st_size > 0:
            print("Refusing to overwrite existing reading.db without --force", file=sys.stderr)
            raise SystemExit(2)
    with zipfile.ZipFile(src, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/") or name == "BACKUP.txt":
                continue
            if name.startswith("kept/"):
                target = config.KEPT_DIR / Path(name).name
                config.KEPT_DIR.mkdir(parents=True, exist_ok=True)
            elif name.startswith("human/"):
                target = config.AUDIO_HUMAN / Path(name).name
                config.AUDIO_HUMAN.mkdir(parents=True, exist_ok=True)
            elif Path(name).name in KEEP_NAMES:
                target = config.DATA_DIR / Path(name).name
            else:
                continue
            with zf.open(info) as src_f, target.open("wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
            print(f"Restored {target.relative_to(ROOT)}")
    print("Restore complete. Restart the server (./run).")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Backup / restore Reading Buddy data/ and audio/human/"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="Write data/backup-YYYYMMDD-HHMMSS.zip")
    b.add_argument("-o", "--output", type=Path, default=None)
    r = sub.add_parser("restore", help="Restore from a backup zip")
    r.add_argument("zip_path", type=Path)
    r.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "backup":
        backup(args.output)
        return 0
    restore(args.zip_path, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
