# Builds labeled contact sheets from the generated previews for visual QA.
# Output: <out>/ (default <repo>/research/out/sheets/, gitignored — regenerate anytime).
#
# Usage:
#   python tools/make_sheets.py [--repo PATH] [--out DIR] [--per-sheet 100]
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
COLS, THUMB_W, THUMB_H, LABEL_H = 10, 76, 140, 14


def main():
    ap = argparse.ArgumentParser(
        description="Build labeled contact sheets from the canonical preview images for visual QA.")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root with heroes_list.json and assets/heroes/ (default: {REPO})")
    ap.add_argument("--out", type=Path, default=None,
                    help="output dir for the sheets (default: <repo>/research/out/sheets)")
    ap.add_argument("--per-sheet", type=int, default=100,
                    help="thumbnails per sheet (default: 100)")
    args = ap.parse_args()

    sheet_dir = args.out or (args.repo / "research" / "out" / "sheets")
    sheet_dir.mkdir(parents=True, exist_ok=True)
    heroes = json.load(open(args.repo / "heroes_list.json", encoding="utf-8"))
    items = []
    for ns, pack in heroes["packs"].items():
        for h in pack["heroes"]:
            if h.get("image"):
                items.append((h["name"], args.repo / h["image"]))
    print("thumbs:", len(items))

    for i in range(0, len(items), args.per_sheet):
        chunk = items[i:i + args.per_sheet]
        rows = (len(chunk) + COLS - 1) // COLS
        W, H = COLS * THUMB_W, rows * (THUMB_H + LABEL_H)
        sheet = Image.new("RGB", (W, H), (24, 24, 28))
        d = ImageDraw.Draw(sheet)
        for j, (name, p) in enumerate(chunk):
            x, y = (j % COLS) * THUMB_W, (j // COLS) * (THUMB_H + LABEL_H)
            im = Image.open(p).convert("RGBA")
            im.thumbnail((THUMB_W - 4, THUMB_H - 4))
            sheet.paste(im, (x + (THUMB_W - im.width) // 2, y + (THUMB_H - im.height) // 2), im)
            d.text((x + 2, y + THUMB_H + 1), name[:17], fill=(220, 220, 220))
        out = sheet_dir / f"sheet_{i // args.per_sheet + 1:02d}.png"
        sheet.save(out)
        print("saved", out.name)


if __name__ == "__main__":
    main()
