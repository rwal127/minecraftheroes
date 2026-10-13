#!/usr/bin/env python3
"""Automated data checks for the Hero Atlas catalog.

Run from the repository root:  python tests/validate_data.py
Exits non-zero if heroes_list.json is inconsistent or contains obsolete metadata.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "heroes_list.json"
ALIASES = ROOT / "aliases.json"
DESCRIPTIONS = ROOT / "descriptions.json"
STATS = ROOT / "stats.json"
ID_RE = re.compile(r"^[a-z0-9_]+:[a-z0-9_]+$")
FORBIDDEN_KEYS = {"status", "active_total", "marketplace_total", "note", "all_ids"}
HERO_KEYS = {"id", "name", "image", "image_wiki", "image_game", "image_model", "wiki"}
DESC_KEYS = {"dr", "cost"}
TRAIT_KEYS = {"t_melee", "t_speed", "t_tank", "t_jump", "t_archery"}

errors = []


def check(cond: bool, message: str) -> None:
    if cond:
        print(f"  OK   {message}")
    else:
        errors.append(message)
        print(f"  FAIL {message}")


def walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))

    print("heroes_list.json checks:")
    keys = set(walk_keys(data))
    check(not (keys & FORBIDDEN_KEYS), "no obsolete status metadata keys in structure")
    check(set(data) == {"meta", "packs"}, "top-level keys are exactly {meta, packs}")
    check(set(data["meta"]) == {"mod", "command_usage", "generated", "total", "packs", "previews"},
          "meta keys are minimal + previews stats")

    packs = data["packs"]
    ids = [h["id"] for p in packs.values() for h in p["heroes"]]
    total = len(ids)
    check(data["meta"]["total"] == total, f"meta.total ({data['meta']['total']}) == actual hero count ({total})")
    check(data["meta"]["packs"] == len(packs), f"meta.packs ({data['meta']['packs']}) == actual pack count ({len(packs)})")
    check(len(set(ids)) == total, "all hero IDs are unique")
    check(all(ID_RE.match(i) for i in ids), "every ID matches 'packname:heroname'")
    check(all(i.split(":", 1)[0] == ns for ns, p in packs.items() for i in (h["id"] for h in p["heroes"])),
          "every ID's prefix matches its pack key")
    check(all(p["sources"] for p in packs.values()), "every pack lists its source archive")
    check(all(p["count"] == len(p["heroes"]) for p in packs.values()), "per-pack counts are accurate")
    check(all(set(h) == HERO_KEYS and h["name"].strip() for p in packs.values() for h in p["heroes"]),
          f"heroes have exactly {sorted(HERO_KEYS)} and non-empty names")

    print("\npreview image checks:")
    imgs = [h[k] for p in packs.values() for h in p["heroes"] for k in ("image", "image_wiki", "image_game", "image_model") if h[k]]
    bad = [p for p in imgs if not p.startswith("assets/heroes/")]
    check(not bad, f"all image paths live under assets/heroes/ (bad: {bad[:3]})")
    missing = [p for p in set(imgs) if not (ROOT / p).is_file()]
    check(not missing, f"every referenced image exists on disk (missing: {missing[:3]})")
    with_preview = sum(1 for p in packs.values() for h in p["heroes"] if h["image"])
    check(data["meta"]["previews"]["total_with_preview"] == with_preview,
          f"meta.previews.total_with_preview ({data['meta']['previews']['total_with_preview']}) == heroes with a canonical image ({with_preview})")
    check(all(h["wiki"] is None or h["wiki"].startswith("https://fiskheroes.fandom.com/wiki/")
              for p in packs.values() for h in p["heroes"]),
          "wiki links point at fiskheroes.fandom.com")
    print(f"  {with_preview}/{total} heroes with a canonical preview, {len(set(imgs))} image files referenced")

    try:
        from PIL import Image
    except ImportError:
        print("  SKIP image decoding check (PIL is not installed)")
    else:
        broken = []
        for rel in sorted(set(imgs)):
            try:
                with Image.open(ROOT / rel) as im:
                    im.load()  # full decode: catches truncated/corrupt files
                    if im.width <= 0 or im.height <= 0:
                        broken.append(rel)
            except Exception:
                broken.append(rel)
        check(not broken, f"every referenced image decodes with PIL (broken: {broken[:3]})")

    print(f"\n{total} heroes across {len(packs)} packs")

    if ALIASES.exists():
        print("aliases.json checks:")
        alias_map = json.loads(ALIASES.read_text(encoding="utf-8"))
        unknown = sorted(set(alias_map) - set(ids))
        check(not unknown, f"all alias keys are known hero IDs (unknown: {unknown[:5]})")
        check(set(ids) == set(alias_map), "every hero has an alias entry (possibly empty)")
        non_lower = [(k, a) for k, v in alias_map.items() for a in v if a != a.lower()]
        check(not non_lower, f"all aliases are lowercase (bad: {non_lower[:3]})")
        check(all(isinstance(v, list) and all(isinstance(a, str) for a in v) for v in alias_map.values()),
              "alias values are lists of strings")
        print(f"  {sum(len(v) for v in alias_map.values())} aliases for {sum(1 for v in alias_map.values() if v)}/{len(alias_map)} heroes")
    else:
        print("aliases.json: not found (optional)")

    if DESCRIPTIONS.exists():
        print("descriptions.json checks:")
        descs = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))
        unknown = sorted(set(descs) - set(ids))
        check(not unknown, f"all description keys are known hero IDs (unknown: {unknown[:5]})")
        check(all(set(v) <= DESC_KEYS for v in descs.values()),
              f"description entries only use keys {sorted(DESC_KEYS)}")
        check(all(isinstance(v.get("dr"), (int, float)) and 0 < v["dr"] < 100 for v in descs.values() if "dr" in v),
              "damage reduction is a percentage")
        print(f"  {len(descs)} wiki-only numbers ({sum(1 for v in descs.values() if 'dr' in v)} with dr, "
              f"{sum(1 for v in descs.values() if 'cost' in v)} with cost)")
    else:
        print("descriptions.json: not found (optional)")

    if STATS.exists():
        print("stats.json checks:")
        stats = json.loads(STATS.read_text(encoding="utf-8"))
        missing = sorted(set(ids) - set(stats))
        check(not missing, f"every hero has a stats entry (missing: {missing[:5]})")
        unknown = sorted(set(stats) - set(ids))
        check(not unknown, f"all stats keys are known hero IDs (unknown: {unknown[:5]})")
        check(all(set(v) <= {"tier", "abilities", "traits"} for v in stats.values()),
              "stats entries only use keys {abilities, tier, traits}")
        bad_tier = [k for k, v in stats.items() if "tier" in v and v["tier"] is not None
                    and (not isinstance(v["tier"], int) or not 1 <= v["tier"] <= 10)]
        check(not bad_tier, f"tiers are integers 1..10 or null (bad: {bad_tier[:5]})")
        bad_abilities = [k for k, v in stats.items()
                         if not isinstance(v.get("abilities"), list)
                         or not all(isinstance(a, str) and a.strip() for a in v["abilities"])]
        check(not bad_abilities, f"abilities are lists of non-empty strings (bad: {bad_abilities[:5]})")
        bad_traits = [k for k, v in stats.items()
                      if not set(v.get("traits", [])) <= TRAIT_KEYS]
        check(not bad_traits, f"traits use known keys {sorted(TRAIT_KEYS)} (bad: {bad_traits[:5]})")
        print(f"  {len(stats)} hero stat entries "
              f"({sum(1 for v in stats.values() if v.get('tier') is not None)} with tier, "
              f"{sum(1 for v in stats.values() if v.get('abilities'))} with abilities, "
              f"{sum(1 for v in stats.values() if v.get('traits'))} with traits)")
    else:
        print("stats.json: not found (optional)")

    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
