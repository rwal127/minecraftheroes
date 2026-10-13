# Generates front-view suit previews for every hero (built-in + heropacks) from the
# textures inside the mod jar / heropack zips. Suit textures use the Minecraft skin
# layout (64x64 or 64x32, scaled variants too); the hero's model json tells which
# textures stack onto which render layer. Output: <repo>/assets/heroes/game/<ns>__<id>.png
#
# Usage:
#   python tools/hero_previews_game.py --mc-root "C:\Games\Minecraft"
# The game install (mod jar + heropacks) is not committed; pass --mc-root or set MC_ROOT.
import argparse
import collections
import io
import json
import os
import re
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent

# front-view regions in a 64x64 skin layout: (x, y, w, h)
REG64 = {
    "head": (8, 8, 8, 8),
    "body": (20, 20, 8, 12),
    "arm_r": (44, 20, 4, 12),
    "arm_l": (36, 52, 4, 12),
    "leg_r": (4, 20, 4, 12),
    "leg_l": (20, 52, 4, 12),
}
SCALE = 4  # pixels per texture pixel in the output preview

texture_index = {}  # open ZipFile -> {texture basename: [full paths]}


# Heroes whose in-game look is a custom Tabula model, not the player skin: the texture
# composer either fails them or shows the untransformed stand-in (Hulk -> Banner), so
# don't emit game previews for them — tools/hero_previews_models.py renders their models.
GAME_SKIP = {
    "tgheroes:hulk", "tgheroes:red_hulk", "tgheroes:jugger", "tgheroes:thanos",
    "tgheroes:thing", "tgheroes:mr_fantastic", "tgheroes:abomation", "tgheroes:modok",
    "tgheroes:psylocke", "tgheroes:magik", "tgheroes:fff",
    "jmctheroes:modok", "jmctheroes:hit_monkey", "jmctheroes:pork_grind",
    "jmctheroes:spider_ham", "jmctheroes:ultron_mk1", "jmctheroes:groot",
    "pwt:halloween_ghost", "pwt:halloween_scarecrow", "pwt:joker_cyberpunk", "pwt:toxin",
    "skarlet:the_thing",
}


def parse_args():
    ap = argparse.ArgumentParser(
        description="Generate front-view suit previews from the textures inside the mod jar / heropacks.")
    ap.add_argument("sample", nargs="?", default=None,
                    help="optional comma-separated hero ids (without namespace) to regenerate; default: all")
    ap.add_argument("--mc-root", default=os.environ.get("MC_ROOT"),
                    help="path to the local game install holding the mod jar and heropacks (env: MC_ROOT)")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    args = ap.parse_args()
    if not args.mc_root:
        ap.error("--mc-root (or the MC_ROOT env var) is required: path to the game install "
                 "with versions/SuperHERO/mods and versions/SuperHERO/fiskheroes")
    args.mc_root = Path(args.mc_root)
    return args


def load_rgba(data):
    return Image.open(io.BytesIO(data)).convert("RGBA")


def tex_path(tex_id: str) -> str | None:
    """'fiskheroes:the_flash_layer1' -> assets/.../textures/heroes/....png; None for procedural.
    Names may contain subfolders, e.g. 'misc:adam/black_adam'."""
    if ":" not in tex_id:
        return None
    ns, name = tex_id.split(":", 1)
    if name.endswith(".tx.json") or name.startswith("null"):
        return None
    return f"assets/{ns}/textures/heroes/{name}.png"


def model_texture_stack(model: dict):
    """Order textures bottom-to-top as the model json prescribes. Returns resource
    texture ids (may contain duplicates/None entries which callers skip)."""
    resources = model.get("resources", {})
    tex = model.get("texture", {})
    stack = []

    default = tex.get("default")
    if isinstance(default, str):
        stack.append(default)
    if not stack:
        stack.append("layer1")  # hero_basic / hero_speedster convention

    # overlay layer2 when the parent model would draw it and nothing else uses it
    used = {stack[0]}
    for rl in (tex.get("renderLayer") or {}).values():
        rl_default = rl.get("default") if isinstance(rl, dict) else rl
        if isinstance(rl_default, str):
            stack.append(rl_default)
    if "layer2" in resources and not any(s == "layer2" for s in stack):
        stack.append("layer2")

    lights = model.get("lights", {})
    if isinstance(lights, str):
        stack.append(lights)
    else:
        ldefault = lights.get("default")
        if isinstance(ldefault, str):
            stack.append(ldefault)
        for rl in (lights.get("renderLayer") or {}).values():
            rl_default = rl.get("default") if isinstance(rl, dict) else rl
            if isinstance(rl_default, str):
                stack.append(rl_default)
    return [resources.get(s, s) for s in stack if s and s != "null"]


def renderer_texture_stack(archive, ns: str, hid: str):
    """renderers/heroes/<hid>.js -> loadTextures({...}) entries; layer1/layer2 are the
    standard player-model textures."""
    p = f"assets/{ns}/renderers/heroes/{hid}.js"
    if p not in archive.namelist():
        return []
    m = re.search(r"loadTextures\(\{(.*?)\}\)", archive.read(p).decode("utf-8", errors="replace"), re.S)
    if not m:
        return []
    pairs = dict(re.findall(r'"(\w+)"\s*:\s*"([\w:./-]+)"', m.group(1)))
    stack = []
    for key in ("layer1", "base", "base_0"):  # first hit wins: the base skin texture
        if key in pairs:
            stack.append(tex_path(pairs[key]))
            break
    if "layer2" in pairs:  # overlay
        stack.append(tex_path(pairs["layer2"]))
    return [s for s in stack if s]


def renderer_texture_pairs(archive, ns: str, hid: str):
    """renderers/heroes/<hid>.js loadTextures({...}) as an ordered (key, path) list."""
    p = f"assets/{ns}/renderers/heroes/{hid}.js"
    if p not in archive.namelist():
        return []
    m = re.search(r"loadTextures\(\{(.*?)\}\)", archive.read(p).decode("utf-8", errors="replace"), re.S)
    if not m:
        return []
    return re.findall(r'"(\w+)"\s*:\s*"([\w:./-]+)"', m.group(1))


def default_head(s):
    """Procedural generic player face (8x8, scaled): what an unmasked player's head
    looks like in game. Our own pixel art - no Mojang textures are committed."""
    px = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    p = px.load()
    SKIN, SKIN_D = (199, 138, 94, 255), (176, 118, 78, 255)
    HAIR, WHITE = (59, 42, 30, 255), (238, 238, 238, 255)
    EYE, MOUTH = (72, 58, 138, 255), (150, 96, 66, 255)
    for x in range(8):
        for y in range(8):
            p[x, y] = SKIN
    for x in range(8):          # hair fringe
        p[x, 0] = HAIR
    for x in (0, 1, 6, 7):      # sideburns
        p[x, 1] = HAIR
    p[0, 2] = HAIR; p[7, 2] = HAIR
    p[1, 4] = WHITE; p[2, 4] = EYE   # eyes: white + iris
    p[5, 4] = EYE; p[6, 4] = WHITE
    p[3, 5] = SKIN_D; p[4, 5] = SKIN_D
    p[3, 6] = MOUTH; p[4, 6] = MOUTH
    return px.resize((8 * s, 8 * s), Image.NEAREST)


def compose_canvas(archive, stack):
    """Alpha-composite the texture stack (bottom to top); None if nothing loads."""
    names = set(archive.namelist())
    layers = [load_rgba(archive.read(p)) for p in stack if p in names]
    if not layers:
        return None
    canvas = Image.new("RGBA", layers[0].size, (0, 0, 0, 0))
    for im in layers:
        if im.size == canvas.size:
            canvas.alpha_composite(im)
    return canvas


def gate_passes(canvas):
    """Quality gate: a real player-model suit fills the torso/limb UV areas almost
    completely; custom tabula models and blank/effect textures leave fragments there."""
    s = canvas.width / 64  # texture scale (2x textures are 128 wide, etc.)

    def coverage(part):
        x, y, w, h = (int(v * s) for v in REG64[part])
        region = canvas.crop((x, y, x + w, y + h))
        hist = region.getchannel("A").histogram()
        filled = sum(hist[17:])  # pixels with alpha > 16
        return filled / (w * h)

    cov = {p: coverage(p) for p in ("head", "body", "arm_r", "leg_r")}
    if os.environ.get("PREVIEW_DEBUG"):
        print(f"  COV head={cov['head']:.2f} body={cov['body']:.2f} "
              f"arm={cov['arm_r']:.2f} leg={cov['leg_r']:.2f}")
    # the head region is often transparent on purpose: unmasked heroes render the
    # player's own head there, and cowls/capes can be separate custom meshes
    return cov["body"] >= 0.55 and cov["arm_r"] >= 0.2 and cov["leg_r"] >= 0.2


def front_view(canvas):
    s = canvas.width / 64

    def box(part):
        x, y, w, h = (int(v * s) for v in REG64[part])
        return (x, y, x + w, y + h)
    has64 = canvas.height > 32 * s

    front = Image.new("RGBA", (16, 32), (0, 0, 0, 0))
    front.paste(canvas.crop(box("head")), (4, 0))
    front.paste(canvas.crop(box("body")), (4, 8))
    front.paste(canvas.crop(box("arm_r")), (0, 8))
    front.paste(canvas.crop(box("leg_r")), (4, 20))
    if has64:
        front.paste(canvas.crop(box("arm_l")), (12, 8))
        front.paste(canvas.crop(box("leg_l")), (8, 20))
    else:  # 64x32: left limbs mirror the right ones
        front.paste(canvas.crop(box("arm_r")).transpose(Image.FLIP_LEFT_RIGHT), (12, 8))
        front.paste(canvas.crop(box("leg_r")).transpose(Image.FLIP_LEFT_RIGHT), (8, 20))

    out = Image.new("RGBA", (16 * SCALE + 8, 32 * SCALE + 8), (0, 0, 0, 0))
    out.alpha_composite(front.resize((16 * SCALE, 32 * SCALE), Image.NEAREST), (4, 4))
    return out


def composite_suit(archive, ns: str, hid: str):
    model_name = f"assets/{ns}/models/heroes/{hid}.json"
    candidates = []
    if model_name in archive.namelist():
        try:
            model = json.loads(archive.read(model_name))
            candidates = [tex_path(t) for t in model_texture_stack(model)]
        except Exception:
            candidates = []
    candidates = [c for c in candidates if c]
    if not candidates:
        candidates = renderer_texture_stack(archive, ns, hid)
    if not candidates:  # convention fallback, searching subfolders too
        pats = [f"{hid}_layer1.png", f"{hid}.png", f"{hid}_l1.png",
                f"{hid}_layer2.png", f"{hid}_l2.png"]
        found = {p: texture_index[archive].get(p, []) for p in pats}
        candidates = (found[f"{hid}_layer1.png"][:1] + found[f"{hid}.png"][:1]
                      + found[f"{hid}_l1.png"][:1] + found[f"{hid}_layer2.png"][:1]
                      + found[f"{hid}_l2.png"][:1])
        if not candidates:
            return None

    stacks = [candidates]
    # second chance: many renderers keep the base skin in a non-layer1 key (their
    # layer1 is a blank/procedural stand-in), and slim-arm suits paint the limbs in a
    # separate texture. Try single textures and base+overlay combos before giving up.
    pairs = [(k, tex_path(v)) for k, v in renderer_texture_pairs(archive, ns, hid)]
    pairs = [(k, p) for k, p in pairs if p]
    base = next(iter(dict.fromkeys(candidates)), None)
    for p in [p for _k, p in pairs]:                       # single textures
        if [p] not in stacks:
            stacks.append([p])
    for p in [p for _k, p in pairs]:                       # base + one overlay
        if base and p != base and [base, p] not in stacks:
            stacks.append([base, p])

    for stack in stacks[:14]:
        canvas = compose_canvas(archive, stack)
        if canvas is None:
            continue
        if gate_passes(canvas):
            # the player's own head sits under the suit head in game: cowls leave
            # transparent eye holes (The Flash), some helmets don't paint a head at all
            # (Black Adam). Always draw the procedural head underneath - opaque suit
            # pixels simply cover it.
            s = max(1, round(canvas.width / 64))
            x0, y0, side = 8 * s, 8 * s, 8 * s
            under = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            under.paste(default_head(s), (x0, y0))
            under.alpha_composite(canvas)
            canvas = under
            return front_view(canvas)
    return None


def main():
    args = parse_args()
    out = args.repo / "assets" / "heroes" / "game"
    jar = args.mc_root / "versions/SuperHERO/mods/FiskHeroes-1.7.10-2.4.0.jar"
    packs = args.mc_root / "versions/SuperHERO/fiskheroes"
    if not jar.is_file():
        raise SystemExit(f"mod jar not found: {jar}")

    out.mkdir(parents=True, exist_ok=True)
    sources = {"fiskheroes": zipfile.ZipFile(jar)}

    def register(zpath: Path):
        zf = zipfile.ZipFile(zpath)  # stays open for the whole run
        nss = {m.group(1) for n in zf.namelist()
               if (m := re.match(r"^assets/([a-z0-9_]+)/data/heroes/", n))}
        for ns in nss:
            sources[ns] = zf
            texture_index[zf] = {}
            for n in zf.namelist():
                if n.startswith(f"assets/{ns}/textures/heroes/") and n.endswith(".png"):
                    texture_index[zf].setdefault(n.split("/")[-1], []).append(n)

    texture_index.clear()
    register(jar)
    for z in sorted(packs.glob("*.zip")):
        register(z)
    marketplace = packs / ".marketplace"
    if marketplace.is_dir():
        for z in sorted(marketplace.glob("*.zip")):
            register(z)

    heroes = json.load(open(args.repo / "heroes_list.json", encoding="utf-8"))
    sample = set(args.sample.split(",")) if args.sample else None
    stats = collections.Counter()
    no_texture = []
    for ns, pack in heroes["packs"].items():
        archive = sources.get(ns)
        if archive is None:
            continue
        for h in pack["heroes"]:
            hid = h["id"].split(":", 1)[1]
            if sample and hid not in sample:
                continue
            if h["id"] in GAME_SKIP and not sample:
                continue
            try:
                preview = composite_suit(archive, ns, hid)
            except Exception as e:
                preview = None
                print(f"  !! {h['id']}: {e}")
            if preview is None:
                no_texture.append(h["id"])
                continue
            preview.save(out / f"{ns}__{hid}.png")
            stats[ns] += 1
    for zf in set(sources.values()):
        zf.close()

    total = sum(stats.values())
    print(f"generated {total} previews -> {out.relative_to(args.repo)}/")
    for ns, c in stats.most_common():
        print(f"  {ns:20s} {c}")
    print(f"heroes without suit texture: {len(no_texture)}")
    for x in no_texture[:40]:
        print("   -", x)
    dump = args.repo / "research" / "out" / "no_texture_heroes.json"
    dump.parent.mkdir(parents=True, exist_ok=True)
    json.dump(no_texture, open(dump, "w"), indent=1)


if __name__ == "__main__":
    main()
