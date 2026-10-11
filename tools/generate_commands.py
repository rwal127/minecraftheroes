#!/usr/bin/env python3
"""Regenerates hero_atlas_commands.txt from heroes_list.json.

Run from the repository root:  python tools/generate_commands.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "heroes_list.json"
OUT = ROOT / "hero_atlas_commands.txt"

DISPLAY = {
    "fiskheroes": "FiskHeroes", "misc": "Miscellaneous", "morningstar": "Morningstar",
    "tgheroes": "TGHeroes", "8thpack": "8thPack", "dhhp": "DERPZ Heroes",
    "ironmaniac": "Iron Maniac", "jmctheroes": "JMCT Heroes", "nameless": "Nameless Heroes",
    "ninjago": "Ninjago", "runnyhero": "RunnyHeroes", "sabri": "Sabri Enhanced",
    "secretheroes": "SecretHeroes", "shadows": "Shadows", "sind": "SIND Iron Man",
    "skarlet": "Skarlet", "stellar": "StellarHeroes", "pwt": "The Pack With Things",
    "tmf": "TMF", "transformers_pack": "Transformers Pack", "unconventional": "Unconventional",
}


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    lines = [
        "Hero Atlas Commands",
        "Source: heroes_list.json",
        f"Total heroes: {data['meta']['total']} in {data['meta']['packs']} packs",
        "",
    ]
    for ns, pack in data["packs"].items():
        title = DISPLAY.get(ns, ns)
        lines.append(f"[{title}] ({ns}) — {len(pack['heroes'])}")
        for h in pack["heroes"]:
            lines.append(f"- {h['name']} | {h['id']} | /suit {h['id']}")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {OUT} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
