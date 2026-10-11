# Adds preview images to heroes_list.json using the FiskHeroes wiki
# (https://fiskheroes.fandom.com). The wiki covers only the built-in mod suits; heropack
# heroes keep image: null. Wiki renders are downloaded to assets/heroes/wiki/ (scaled to
# 640px wide); game-texture front views from tools/hero_previews_game.py fill the rest.
#
# Needs the MediaWiki research cache (wiki_research/*.json) from the machine that did the
# one-time wiki research; point WIKI_RESEARCH (or MC_ROOT) at it if not G:\Games\Minecraft.
import csv
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
MC_ROOT = Path(os.environ.get("MC_ROOT", r"G:\Games\Minecraft"))
RESEARCH = Path(os.environ.get("WIKI_RESEARCH", MC_ROOT / "wiki_research"))
OUT_IMG = REPO / "assets" / "heroes"
WIKI = "https://fiskheroes.fandom.com"
UA = {"User-Agent": "Mozilla/5.0"}  # the CDN 403s longer bot-looking UA strings

# hero id (without namespace) -> wiki page title, or ("file", name) when there is no
# usable page (missing page / redirect to another suit). None = no image on the wiki.
WIKI_PAGE = {
    "agent_liberty": None,
    "ant_man": "Ant-Man",
    "anti_monitor": "The Anti-Monitor",
    "arrow": "Arrow",
    "arsenal": "Arsenal",
    "atom": "Atom",
    "atom_smasher": "Atom-Smasher",
    "august_heart_comics": "August Heart (Comics)",
    "batman_dceu": "Batman (DCEU)",
    "black_canary": "Black Canary (Laurel Lance)",
    "black_canary_dinah": "Black Canary",
    "black_lightning": "Black Lightning",
    "black_manta_dceu": None,
    "black_panther": ("file", "Black Panther.png"),
    "captain_america": "Captain America",
    "captain_america_sam": "Captain America (Sam Wilson)",
    "captain_cold": "Captain Cold",
    "chronos": "Chronos",
    "citizen_steel": "Citizen Steel",
    "colossus_xmen": "Colossus",
    "crossbones": None,
    "dark_archer": "Dark Archer",
    "deadpool_xmen": "Deadpool",
    "deathstroke_dceu": None,
    "doctor_octopus": "Doctor Octupus",  # typo preserved from the wiki
    "doctor_strange": "Doctor Strange",
    "falcon": "Falcon",
    "firestorm": "Firestorm (Ronnie Raymond)",
    "firestorm_jax": "Firestorm (Jax Jackson)",
    "geomancer": "Geomancer",
    "godspeed_comics": "Godspeed",
    "green_arrow": "Green Arrow",
    "guardian": "Guardian",
    "harbinger": "Harbinger",
    "heatwave": "Heatwave",
    "iron_man": "Iron Man",
    "iron_man_mk50": "Iron Man (Mark 50)",
    "iron_man_mk85": None,
    "kid_flash": "Kid Flash",
    "killer_frost": "Killer Frost",
    "martian_manhunter": "Martian Manhunter",
    "martian_manhunter_comics": "Martian Manhunter (Comics)",
    "mysterio": "Mysterio",
    "obsidian": "Obsidian",
    "prometheus": "Prometheus",
    "reverse_flash": "Reverse-Flash",
    "rip_hunter": "Rip Hunter",
    "rupture": "Rupture",
    "savitar": ("file", "Savitar.png"),  # the page redirects to Rival, but Savitar.png exists
    "senor_cactus": "Señor Cactus",
    "shazam_dceu": "Shazam (DCEU)",
    "spectre": "Spectre",
    "spider_man": None,
    "spider_man_ps4": None,
    "spider_man_raimi": None,
    "spider_man_webb": None,
    "spodermen": None,
    "the_flash": "The Flash",
    "the_flash_hunter": "The Flash (Hunter Zolomon)",
    "the_flash_jay": "The Flash (Jay Garrick)",
    "the_monitor": "The Monitor",
    "the_rival": "The Rival",
    "the_tick": "The Tick",
    "trajectory": "Trajectory",
    "vision": "Vision",
    "wild_dog": None,
    "zoom": "Zoom",
}

PREVIEW_WIDTH = 640


def load_json(name):
    return json.load(open(RESEARCH / name, encoding="utf-8"))


def wiki_url(title):
    return f"{WIKI}/wiki/{title.replace(' ', '_')}"


def fetch_file_url(title, all_images):
    """Resolve 'File:X.png' -> (direct url, canonical title) from the allimages dump."""
    wanted = title.removeprefix("File:").lower().replace("_", " ")
    for t, url, _w, _h in all_images:
        if t.removeprefix("File:").lower().replace("_", " ") == wanted:
            return url, t
    return None, None


def download(url, dest: Path) -> bool:
    for attempt in range(4):
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 200 and r.content:
            # the CDN serves WebP regardless of Accept; normalize to the dest extension
            Image.open(io.BytesIO(r.content)).save(dest)
            return True
        time.sleep(1.5 * (attempt + 1))  # the CDN rate-limits rapid requests
    return False


def main(redownload=False):
    heroes = json.load(open(REPO / "heroes_list.json", encoding="utf-8"))
    pages = load_json("wiki_pages.json")          # page title -> preview file, gallery, ...
    all_images = load_json("allimages.json")      # [title, url, w, h]

    wiki_dir = OUT_IMG / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    ok = missing = 0
    for pack in heroes["packs"].values():
        for h in pack["heroes"]:
            ns, hid = h["id"].split(":", 1)
            h["image"] = None
            h["image_wiki"] = None
            h["image_game"] = None
            h["wiki"] = None
            if ns != "fiskheroes":
                continue
            ref = WIKI_PAGE.get(hid, "???")
            if ref == "???":  # new built-in hero without a mapping entry
                print(f"  !! no mapping entry for {h['id']}")
                continue
            if ref is None:
                missing += 1
                continue

            if isinstance(ref, tuple):  # ("file", name) - no page, direct file
                file_title = ref[1]
                page_title = None
            else:
                page_title = ref
                file_title = pages.get(ref, {}).get("preview")
                if file_title:
                    file_title = file_title.removeprefix("File:")

            if not file_title:
                missing += 1
                print(f"  !! page has no preview file: {ref}")
                continue

            url, canonical = fetch_file_url(file_title, all_images)
            if not url:
                missing += 1
                print(f"  !! file not found in allimages: {file_title}")
                continue

            ext = canonical.rsplit(".", 1)[-1].lower()
            dest = wiki_dir / f"{hid}.{ext}"
            if redownload or not dest.exists():
                scaled = re.sub(r"/revision/latest", f"/revision/latest/scale-to-width-down/{PREVIEW_WIDTH}", url, count=1)
                if not download(scaled, dest):
                    print(f"  !! download failed: {scaled}")
                    missing += 1
                    continue
            h["image_wiki"] = dest.relative_to(REPO).as_posix()
            h["wiki"] = wiki_url(page_title) if page_title else None
            ok += 1

    # game-texture front views: the fallback canonical image for everyone who has one
    game_dir = OUT_IMG / "game"
    game_ok = 0
    for pack in heroes["packs"].values():
        for h in pack["heroes"]:
            ns, hid = h["id"].split(":", 1)
            game = game_dir / f"{ns}__{hid}.png"
            if game.exists():
                h["image_game"] = game.relative_to(REPO).as_posix()
                game_ok += 1
            if h["image_wiki"] is None and h["image_game"]:
                h["image"] = h["image_game"]
            elif h["image_wiki"]:
                h["image"] = h["image_wiki"]

    with_preview = sum(1 for p in heroes["packs"].values() for h in p["heroes"] if h["image"])
    wiki_only_count = sum(1 for p in heroes["packs"].values()
                          for h in p["heroes"] if h["image_wiki"] and not h["image_game"])
    game_only_count = sum(1 for p in heroes["packs"].values()
                          for h in p["heroes"] if not h["image_wiki"] and h["image_game"])
    heroes["meta"]["previews"] = {
        "total_with_preview": with_preview,
        "wiki_renders": ok,
        "game_front_views": game_ok,
        "builtins_with_preview": f"{sum(1 for h in heroes['packs']['fiskheroes']['heroes'] if h['image'])}"
                                 f"/{len(heroes['packs']['fiskheroes']['heroes'])}",
        "wiki_source": "fiskheroes.fandom.com — 3D-рендеры, вики описывает только встроенные костюмы",
        "game_source": "фронтальный вид, собранный из текстур костюмов в jar/херопаках",
        "without_preview": heroes["meta"]["total"] - with_preview,
        "without_preview_note": "кастомные Tabula-модели (Hulk, Thanos, MODOK, giant-персонажи), "
                                "предметы-гаджеты и герои вообще без текстур костюма",
    }

    (REPO / "heroes_list.json").write_text(
        json.dumps(heroes, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wiki renders: {ok} ({wiki_only_count} wiki-only), game views: {game_ok} "
          f"({game_only_count} game-only), wiki without image: {missing}")
    print(f"previews: {with_preview}/{heroes['meta']['total']} -> heroes_list.json")
    return ok, missing


if __name__ == "__main__":
    main(redownload="--redownload" in sys.argv)
