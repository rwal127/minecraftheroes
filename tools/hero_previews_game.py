# Generates front-view suit previews for every hero (built-in + heropacks) from the
# textures inside the mod jar / heropack zips. Suit textures use the Minecraft skin
# layout (64x64 or 64x32, scaled variants too); the hero's model json tells which
# textures stack onto which render layer. Output: assets/heroes/game/<ns>__<id>.png
#
# Needs the local game install (jar + heropacks are not committed). Point MC_ROOT
# at it if it is not G:\Games\Minecraft:  set MC_ROOT=D:\Games\Minecraft
import collections
import io
import json
import os
import re
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
MC_ROOT = Path(os.environ.get("MC_ROOT", r"G:\Games\Minecraft"))
OUT = REPO / "assets" / "heroes" / "game"
JAR = MC_ROOT / "versions/SuperHERO/mods/FiskHeroes-1.7.10-2.4.0.jar"
PACKS = MC_ROOT / "versions/SuperHERO/fiskheroes"

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

    names = set(archive.namelist())
    layers = [load_rgba(archive.read(p)) for p in candidates if p in names]
    if not layers:
        return None

    base = layers[0]
    canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    for im in layers:
        if im.size == canvas.size:
            canvas.alpha_composite(im)

    s = canvas.width / 64  # texture scale (2x textures are 128 wide, etc.)

    # quality gate: a real player-model suit fills the torso/limb UV areas almost
    # completely; custom tabula models leave fragments there -> no usable preview
    def coverage(part):
        x, y, w, h = (int(v * s) for v in REG64[part])
        region = canvas.crop((x, y, x + w, y + h))
        px = list(region.getdata())
        filled = sum(1 for r, g, b, a in px if a > 16)
        return filled / len(px)

    cov = {p: coverage(p) for p in ("head", "body", "arm_r", "leg_r")}
    if os.environ.get("PREVIEW_DEBUG"):
        print(f"  COV {ns}:{hid} head={cov['head']:.2f} body={cov['body']:.2f} "
              f"arm={cov['arm_r']:.2f} leg={cov['leg_r']:.2f}")
    # the head region is often transparent on purpose: unmasked heroes render the
    # player's own head there, and cowls/capes can be separate custom meshes
    if cov["body"] < 0.55 or cov["arm_r"] < 0.2 or cov["leg_r"] < 0.2:
        return None

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


def main(sample_only=None):
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {"fiskheroes": zipfile.ZipFile(JAR)}

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
    register(JAR)
    for z in sorted(PACKS.glob("*.zip")):
        register(z)
    for z in sorted((PACKS / ".marketplace").glob("*.zip")):
        register(z)

    heroes = json.load(open(REPO / "heroes_list.json", encoding="utf-8"))
    stats = collections.Counter()
    no_texture = []
    for ns, pack in heroes["packs"].items():
        archive = sources.get(ns)
        if archive is None:
            continue
        for h in pack["heroes"]:
            hid = h["id"].split(":", 1)[1]
            if sample_only and hid not in sample_only:
                continue
            try:
                preview = composite_suit(archive, ns, hid)
            except Exception as e:
                preview = None
                print(f"  !! {h['id']}: {e}")
            if preview is None:
                no_texture.append(h["id"])
                continue
            dest = OUT / f"{ns}__{hid}.png"
            preview.save(dest)
            stats[ns] += 1
    for zf in set(sources.values()):
        zf.close()

    total = sum(stats.values())
    print(f"generated {total} previews -> {OUT.relative_to(REPO)}/")
    for ns, c in stats.most_common():
        print(f"  {ns:20s} {c}")
    print(f"heroes without suit texture: {len(no_texture)}")
    for x in no_texture[:40]:
        print("   -", x)
    dump = REPO / "research" / "out" / "no_texture_heroes.json"
    dump.parent.mkdir(parents=True, exist_ok=True)
    json.dump(no_texture, open(dump, "w"), indent=1)


if __name__ == "__main__":
    import sys
    sample = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else None
    main(sample_only=sample)
