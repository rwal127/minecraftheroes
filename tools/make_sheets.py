# Builds labeled contact sheets from the generated previews for visual QA.
# Output: research/out/sheets/ (gitignored — regenerate whenever needed).
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
SHEET_DIR = REPO / "research" / "out" / "sheets"
COLS, THUMB_W, THUMB_H, LABEL_H = 10, 76, 140, 14


def sheets(per_sheet=100):
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
    heroes = json.load(open(REPO / "heroes_list.json", encoding="utf-8"))
    items = []
    for ns, pack in heroes["packs"].items():
        for h in pack["heroes"]:
            if h.get("image"):
                items.append((h["name"], REPO / h["image"]))
    print("thumbs:", len(items))

    for i in range(0, len(items), per_sheet):
        chunk = items[i:i + per_sheet]
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
        out = SHEET_DIR / f"sheet_{i // per_sheet + 1:02d}.png"
        sheet.save(out)
        print("saved", out.name)


if __name__ == "__main__":
    sheets(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
