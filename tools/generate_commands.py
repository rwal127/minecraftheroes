#!/usr/bin/env python3
"""Regenerates hero_atlas_commands.txt from heroes_list.json.

Usage:
  python tools/generate_commands.py [--repo PATH]
"""
import argparse
from pathlib import Path

import json

REPO = Path(__file__).resolve().parent.parent

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
    ap = argparse.ArgumentParser(description="Regenerate hero_atlas_commands.txt from heroes_list.json.")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    args = ap.parse_args()

    data = json.loads((args.repo / "heroes_list.json").read_text(encoding="utf-8"))
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
    out = args.repo / "hero_atlas_commands.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
