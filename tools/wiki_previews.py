# Adds preview images to heroes_list.json using the FiskHeroes wiki
# (https://fiskheroes.fandom.com). The wiki covers only the built-in mod suits; heropack
# heroes keep image: null. Wiki renders are downloaded to <repo>/assets/heroes/wiki/
# (scaled to 640px wide); game-texture front views from tools/hero_previews_game.py fill
# the rest. After the run heroes_list.json holds the image/image_wiki/image_game/wiki
# fields and meta.previews stats.
#
# Usage:
#   python tools/wiki_previews.py --mc-root "C:\Games\Minecraft"
# The MediaWiki research cache (wiki_research/*.json) was produced by a one-time wiki
# crawl; it defaults to <mc-root>/wiki_research and can be overridden with --wiki-research.
import argparse
import io
import json
import os
import re
import time
from pathlib import Path

import requests
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
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


def parse_args():
    ap = argparse.ArgumentParser(
        description="Download wiki suit renders and merge preview fields into heroes_list.json.")
    ap.add_argument("--mc-root", default=None,
                    help="path to the local game install; only used to locate the wiki research "
                         "cache (env: MC_ROOT)")
    ap.add_argument("--wiki-research", type=Path, default=None,
                    help=f"path to the wiki research cache dir with allimages.json / wiki_pages.json "
                         f"(env: WIKI_RESEARCH; default: <mc-root>/wiki_research)")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    ap.add_argument("--redownload", action="store_true",
                    help="re-download renders even if the files already exist")
    args = ap.parse_args()

    mc_root = args.mc_root or os.environ.get("MC_ROOT")
    if args.wiki_research:
        args.research = args.wiki_research
    else:
        env = os.environ.get("WIKI_RESEARCH")
        if env:
            args.research = Path(env)
        elif mc_root:
            args.research = Path(mc_root) / "wiki_research"
        else:
            ap.error("the wiki research cache is required: pass --wiki-research, set WIKI_RESEARCH, "
                     "or point --mc-root/MC_ROOT at the game install containing wiki_research/")
    args.research = Path(args.research)
    return args


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


def main():
    args = parse_args()
    repo, research = args.repo, args.research
    heroes = json.load(open(repo / "heroes_list.json", encoding="utf-8"))
    pages = json.load(open(research / "wiki_pages.json", encoding="utf-8"))   # page title -> preview file, ...
    all_images = json.load(open(research / "allimages.json", encoding="utf-8"))  # [title, url, w, h]

    wiki_dir = repo / "assets" / "heroes" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    ok = missing = 0
    for pack in heroes["packs"].values():
        for h in pack["heroes"]:
            ns, hid = h["id"].split(":", 1)
            h["image"] = None
            h["image_wiki"] = None
            h["image_game"] = None
            h["image_model"] = None
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
            if args.redownload or not dest.exists():
                scaled = re.sub(r"/revision/latest", f"/revision/latest/scale-to-width-down/{PREVIEW_WIDTH}", url, count=1)
                if not download(scaled, dest):
                    print(f"  !! download failed: {scaled}")
                    missing += 1
                    continue
            h["image_wiki"] = dest.relative_to(repo).as_posix()
            h["wiki"] = wiki_url(page_title) if page_title else None
            ok += 1

    # game-texture front views + custom Tabula model renders: fallback canonical images
    game_dir = repo / "assets" / "heroes" / "game"
    model_dir = repo / "assets" / "heroes" / "models"
    game_ok = model_ok = 0
    for pack in heroes["packs"].values():
        for h in pack["heroes"]:
            ns, hid = h["id"].split(":", 1)
            game = game_dir / f"{ns}__{hid}.png"
            if game.exists():
                h["image_game"] = game.relative_to(repo).as_posix()
                game_ok += 1
            model = model_dir / f"{ns}__{hid}.png"
            if model.exists():
                h["image_model"] = model.relative_to(repo).as_posix()
                model_ok += 1
            if h["image_wiki"]:
                h["image"] = h["image_wiki"]
            elif h["image_game"]:
                h["image"] = h["image_game"]
            elif h.get("image_model"):
                h["image"] = h["image_model"]

    with_preview = sum(1 for p in heroes["packs"].values() for h in p["heroes"] if h["image"])
    wiki_only_count = sum(1 for p in heroes["packs"].values()
                          for h in p["heroes"] if h["image_wiki"] and not h["image_game"])
    game_only_count = sum(1 for p in heroes["packs"].values()
                          for h in p["heroes"] if not h["image_wiki"] and h["image_game"])
    heroes["meta"]["previews"] = {
        "total_with_preview": with_preview,
        "wiki_renders": ok,
        "game_front_views": game_ok,
        "model_renders": model_ok,
        "builtins_with_preview": f"{sum(1 for h in heroes['packs']['fiskheroes']['heroes'] if h['image'])}"
                                 f"/{len(heroes['packs']['fiskheroes']['heroes'])}",
        "wiki_source": "fiskheroes.fandom.com — 3D-рендеры, вики описывает только встроенные костюмы",
        "game_source": "фронтальный вид, собранный из текстур костюмов в jar/херопаках",
        "model_source": "офлайн-рендер Tabula-моделей из херопаков (tools/hero_previews_models.py)",
        "without_preview": heroes["meta"]["total"] - with_preview,
        "without_preview_note": "кастомные модели без превью-геометрии, предметы-гаджеты и герои "
                                "вообще без текстур костюма",
    }

    (repo / "heroes_list.json").write_text(
        json.dumps(heroes, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wiki renders: {ok} ({wiki_only_count} wiki-only), game views: {game_ok} "
          f"({game_only_count} game-only), model renders: {model_ok}, wiki without image: {missing}")
    print(f"previews: {with_preview}/{heroes['meta']['total']} -> heroes_list.json")
    return ok, missing


if __name__ == "__main__":
    main()
