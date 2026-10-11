# Builds descriptions.json: per-hero suit stats scraped from the FiskHeroes wiki suit
# pages (the same info the wiki shows per suit: tier, damage reduction, Tutridium cost,
# power groups). Only built-in suits have wiki pages; heropack heroes get a localized
# template description in the UI instead.
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

# Suits page: tier -> damage reduction (a tier is a damage-reduction band)
TIER_DR = {1: 75.0, 2: 80.8, 3: 85.2, 4: 88.6, 5: 91.2, 6: 93.3, 7: 94.8, 8: 96.0, 9: 96.9, 10: 97.6}


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
    """Extract (tier, damage reduction %, Tutridium cost, power groups, intro) from a
    suit page."""
    text = strip_markup(wt)
    desc = {}

    m = re.search(r"is a Tier (\d+) character", text)
    if m:
        desc["tier"] = int(m.group(1))

    m = re.search(r"\+\s*([\d.]+)\s*% Damage Reduction", text)
    if m:
        desc["dr"] = float(m.group(1))
        if "tier" not in desc:  # DR -> nearest tier band
            desc["tier"] = min(TIER_DR, key=lambda t: abs(TIER_DR[t] - desc["dr"]))

    m = re.search(r"==\s*'?Cost'?\s*==\s*\n+\s*(\d+)\s+Tutridium", text)
    if m:
        desc["cost"] = int(m.group(1))

    # power groups: top-level bold bullets of the Powers & Abilities section
    # (stat bullets like "* + 85% Damage Reduction" are excluded)
    m = re.search(r"==\s*'''Powers & Abilities'''\s*==(.*?)(?=\n==\s*'''[^=]|\Z)", wt, re.S)
    if m:
        powers = [p for p in re.findall(r"^\* ?'''([^']+?)'''", m.group(1), re.M)
                  if not p.startswith("+") and p.strip() not in ("Stats", "Effects")]
        if powers:
            desc["powers"] = powers

    # lead-section paragraphs minus the "X is a Tier N" line and confusion notes
    lead = wt.split("==", 1)[0]
    lead = strip_markup(lead)
    paras = [re.sub(r"\s+", " ", p).strip() for p in lead.split("\n\n")]
    paras = [p for p in paras
             if p and not re.search(r"is a Tier \d+ character", p) and not p.startswith("Note:")]
    if paras:
        desc["note"] = paras[0][:400]

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
    print(f"descriptions: {len(out)}/{len(builtins)} built-in heroes -> descriptions.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Build descriptions.json from the FiskHeroes wiki suit pages.")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch page wikitext even if cached")
    a = ap.parse_args()
    main(refresh=a.refresh, repo=a.repo)
