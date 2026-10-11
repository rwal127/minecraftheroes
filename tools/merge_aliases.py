#!/usr/bin/env python3
"""Merges research/out/agent_*.json into aliases.json (hero_id -> [search aliases]).

Usage:
  python tools/merge_aliases.py [--repo PATH]
Aliases for hero IDs missing from heroes_list.json are reported and dropped.
"""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge research/out/agent_*.json into aliases.json.")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    args = ap.parse_args()

    catalog = json.loads((args.repo / "heroes_list.json").read_text(encoding="utf-8"))
    known = {h["id"] for p in catalog["packs"].values() for h in p["heroes"]}

    merged: dict[str, list[str]] = {}
    dropped: list[str] = []
    research_dir = args.repo / "research" / "out"
    files = sorted(research_dir.glob("agent_*.json"))
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
    out = args.repo / "aliases.json"
    out.write_text(json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {out}: {len(merged)} heroes, {total_aliases} aliases from {len(files)} files")
    if dropped:
        print(f"dropped unknown hero IDs: {sorted(set(dropped))}")
    covered = sum(1 for v in merged.values() if v)
    print(f"heroes with aliases: {covered}/{len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
