#!/usr/bin/env python3
"""Merges research/out/agent_*.json into aliases.json (hero_id -> [search aliases]).

Run from the repository root:  python tools/merge_aliases.py
Aliases for hero IDs missing from heroes_list.json are reported and dropped.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "research" / "out"
CATALOG = ROOT / "heroes_list.json"
OUT = ROOT / "aliases.json"


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    known = {h["id"] for p in catalog["packs"].values() for h in p["heroes"]}

    merged: dict[str, list[str]] = {}
    dropped: list[str] = []
    files = sorted(IN.glob("agent_*.json"))
    if not files:
        print("no research/out/agent_*.json files found")
        return 1
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for ns, heroes in data.items():
            for sid, aliases in heroes.items():
                hid = f"{ns}:{sid}"
                if hid not in known:
                    dropped.append(hid)
                    continue
                bucket = merged.setdefault(hid, [])
                for a in aliases:
                    a = str(a).strip().lower()
                    if a and a not in bucket:
                        bucket.append(a)

    for hid in known:
        merged.setdefault(hid, [])

    total_aliases = sum(len(v) for v in merged.values())
    OUT.write_text(json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {OUT}: {len(merged)} heroes, {total_aliases} aliases from {len(files)} files")
    if dropped:
        print(f"dropped unknown hero IDs: {sorted(set(dropped))}")
    covered = sum(1 for v in merged.values() if v)
    print(f"heroes with aliases: {covered}/{len(merged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
