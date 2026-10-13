# Builds descriptions.json: per-hero wiki-only numbers for built-in suits —
# damage reduction and Tutridium cost scraped from the FiskHeroes wiki suit
# pages. Tier and abilities are NOT taken from the wiki: they come from the
# game's own hero definitions via tools/fetch_hero_stats.py (stats.json), and
# the UI composes localized template descriptions from that data.
#
# Usage:
#   python tools/fetch_descriptions.py [--repo PATH] [--refresh]
# Page wikitext is cached in <repo>/research/out/wiki_suit_pages.json, so re-runs don't
# hit the wiki again (pass --refresh to re-fetch).
import argparse
import json
import re
import time
from pathlib import Path

import requests

from wiki_previews import WIKI_PAGE, UA, WIKI

REPO = Path(__file__).resolve().parent.parent


def fetch_wikitext(title: str, cache: dict, refresh=False) -> str | None:
    if not refresh and title in cache:
        return cache[title]
    for attempt in range(4):
        r = requests.get(
            f"{WIKI}/api.php",
            params={"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
            headers=UA, timeout=60)
        if r.status_code == 200:
            data = r.json()
            wt = data.get("parse", {}).get("wikitext", {}).get("*")
            cache[title] = wt
            time.sleep(1.0)  # be polite to the API
            return wt
        time.sleep(1.5 * (attempt + 1))
    print(f"  !! fetch failed: {title}")
    cache[title] = None
    return None


def strip_markup(wt: str) -> str:
    """Wikitext -> plain-ish text, keeping bold markers out of the way."""
    wt = re.sub(r"<ref[^>]*/>", "", wt)
    wt = re.sub(r"<ref[^>]*>.*?</ref>", "", wt, flags=re.S)
    wt = re.sub(r"\{\{[^{}]*\}\}", "", wt)  # templates (notes, stubs…)
    wt = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", wt)  # [[A|b]] -> b
    wt = wt.replace("'''", "").replace("''", "")
    return wt


def parse_suit_page(wt: str) -> dict | None:
    """Extract (damage reduction %, Tutridium cost) from a suit page."""
    text = strip_markup(wt)
    desc = {}

    m = re.search(r"\+\s*([\d.]+)\s*% Damage Reduction", text)
    if m:
        desc["dr"] = float(m.group(1))

    m = re.search(r"==\s*'?Cost'?\s*==\s*\n+\s*(\d+)\s+Tutridium", text)
    if m:
        desc["cost"] = int(m.group(1))

    return desc or None


def main(refresh=False, repo=REPO):
    heroes = json.load(open(repo / "heroes_list.json", encoding="utf-8"))
    builtins = {h["id"].split(":", 1)[1] for h in heroes["packs"]["fiskheroes"]["heroes"]}

    cache_path = repo / "research" / "out" / "wiki_suit_pages.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = json.load(open(cache_path, encoding="utf-8")) if cache_path.exists() else {}

    out = {}
    for hid in sorted(builtins):
        ref = WIKI_PAGE.get(hid)
        if not isinstance(ref, str):  # None = no page, ("file", …) = file only
            continue
        wt = fetch_wikitext(ref, cache, refresh)
        if not wt:
            continue
        desc = parse_suit_page(wt)
        if desc:
            out[f"fiskheroes:{hid}"] = desc
        else:
            print(f"  !! nothing parsed: {ref}")

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    (repo / "descriptions.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"descriptions: {len(out)}/{len(builtins)} built-in heroes -> descriptions.json "
          f"(dr: {sum(1 for v in out.values() if 'dr' in v)}, cost: {sum(1 for v in out.values() if 'cost' in v)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Build descriptions.json (dr/cost) from the FiskHeroes wiki suit pages.")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch page wikitext even if cached")
    a = ap.parse_args()
    main(refresh=a.refresh, repo=a.repo)
