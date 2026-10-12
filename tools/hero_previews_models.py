# Renders front-view previews for heroes whose suits are custom Tabula models
# (.tbl resources inside the heropacks) — the ones tools/hero_previews_game.py can't
# compose from a player-skin texture layout.
#
# How it works: heropack renderers build custom geometry at runtime by loading .tbl
# model resources (a zip with model.json cube geometry + texture.png) and anchoring
# them to player-model slots ("head", "body", "rightArm", …). This tool parses the
# renderer JS statically, resolves every model effect to its .tbl + texture, places
# anchored parts at the standard ModelBiped rotation points and software-renders an
# orthographic front view of everything in one shared world space (painter's
# algorithm, NEAREST sampling).
#
# Usage:
#   python tools/hero_previews_models.py --mc-root "C:\Games\Minecraft"
# Output: <repo>/assets/heroes/models/<pack>__<hero>.png (+ --sheet for a QA contact sheet)
import argparse
import collections
import io
import json
import math
import os
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent

# ModelBiped rotation points (units of 1/16 block, y down from the neck line).
ANCHORS = {
    "head": (0, 0, 0), "headwear": (0, 0, 0), "hat": (0, 0, 0),
    "body": (0, 0, 0), "root": (0, 0, 0),
    "rightArm": (-5, 2, 0), "leftArm": (5, 2, 0),
    "rightLeg": (-1.9, 12, 0), "leftLeg": (1.9, 12, 0),
}
MAX_EFFECTS = 24          # hard cap: absurd renderer -> skip
MIN_PIXELS = 150          # smaller bbox -> nothing meaningful rendered
MAX_W_H_RATIO = 1.9       # wider than tall by this much -> multi-entity scene (army, portal row)

# hero id -> list of model name fragments to render instead of everything the JS
# mentions, or [] to skip the hero entirely (items, skin-only add-ons, effect props).
# Only needed where the generic heuristic picks wrong (checked on the QA sheet).
OVERRIDES = {
    # gadget items and skin-only add-ons: no meaningful model preview exists
    "misc:mind_stone": [], "misc:power_stone": [], "misc:reality_stone": [],
    "misc:soul_stone": [], "misc:space_stone": [], "misc:time_stone": [],
    "misc:infinity_gauntlet": [], "misc:invincible_variants": [],
    "tgheroes:infinity_gauntlet": [],
    "tgheroes:wasp": [], "tgheroes:vision": [],           # skin + alex arms/wings only
    "jmctheroes:power": [], "jmctheroes:big_wheel": [],
    "shadows:power_ranger_wind_yellow": [], "shadows:power_ranger_wind_blue": [],
    "shadows:power_ranger_wind_red": [], "shadows:backpack": [],
    "jmctheroes:scarlet_spider": [], "sabri:kang_the_conqueror": [],  # effect-only props
    "shadows:hunter": [], "stellar:cloak": [],
    "tmf:the_mandarin_aa": [],
    "unconventional:mosquito": [], "unconventional:nick_fury": [],
    "unconventional:ronin": [], "unconventional:wanda": [],
    # skin + add-on heroes: their look is the player skin (hair/arms/weapon props are
    # modeled separately) -> let the game-texture composer render them instead
    "tgheroes:emma_frost": [], "tgheroes:jean": [], "tgheroes:she_hulk": [], "tgheroes:rogue": [],
    "sabri:black_widow": [], "sabri:doctor_doom_comics": [], "jmctheroes:moon_knight": [],
    # main body parts only: drop banner-form arms / wings / weapon props
    "tgheroes:hulk": ["hulk_"],
    "tgheroes:fff": {"vars": ["foom_"]},  # main foom body, not the fly_* duplicates
    "jmctheroes:groot": ["groothead", "grootchest", "grootrightarm", "grootleftarm", "grootrightleg", "grootleftleg"],
}


def parse_args():
    ap = argparse.ArgumentParser(
        description="Render Tabula-model heroes (.tbl) to front-view previews, no game needed.")
    ap.add_argument("sample", nargs="?", default=None,
                    help="optional comma-separated hero ids (with namespace) to (re)render; default: all heroes without a game preview")
    ap.add_argument("--mc-root", default=os.environ.get("MC_ROOT"),
                    help="path to the local game install holding the heropacks (env: MC_ROOT)")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    ap.add_argument("--sheet", type=Path, default=None,
                    help="also write a QA contact sheet of the renders to this path")
    args = ap.parse_args()
    if not args.mc_root:
        ap.error("--mc-root (or the MC_ROOT env var) is required: path to the game install "
                 "with versions/SuperHERO/fiskheroes")
    args.mc_root = Path(args.mc_root)
    return args


# ---------- tiny 4x4 matrix helpers ----------
def mat_identity():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def mat_translate(x, y, z):
    m = mat_identity()
    m[0][3], m[1][3], m[2][3] = x, y, z
    return m

def mat_scale(s):
    return [[s, 0, 0, 0], [0, s, 0, 0], [0, 0, s, 0], [0, 0, 0, 1]]

def mat_rot(axis, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    if axis == "x":
        return [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]]
    if axis == "y":
        return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]
    return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

def apply(m, p):
    x, y, z = p
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


# ---------- tabula (.tbl) rendering ----------
def load_tbl(zf, path):
    inner = zipfile.ZipFile(io.BytesIO(zf.read(path)))
    model = json.loads(inner.read("model.json"))
    pngs = [n for n in inner.namelist() if n.lower().endswith(".png")]
    tex = Image.open(io.BytesIO(inner.read(pngs[0]))).convert("RGBA") if pngs else None
    return model, tex


def normalize_parts(model):
    """Both Tabula flavors -> a single node tree: {rotP, rotA, boxes, children, showModel, tw, th}.

    Accepts a model dict or a bare list of part/cube dicts. Flavor A ("parts"): rotPX/Y/Z +
    rotAX/Y/Z, boxes with posX.. and expandX.., nested children. Flavor B ("cubes"):
    position/rotation arrays, offset/dimensions arrays, mcScale inflation, txOffset/txMirror,
    hidden flags, nested children."""
    if isinstance(model, dict):
        parts = model.get("parts") or []
        cubes = model.get("cubes") or []
    else:
        parts = model or []
        cubes = []
    nodes = []
    for p in parts:
        nodes.append({"rotP": (p.get("rotPX", 0), p.get("rotPY", 0), p.get("rotPZ", 0)),
                      "rotA": (p.get("rotAX", 0), p.get("rotAY", 0), p.get("rotAZ", 0)),
                      "boxes": p.get("boxes", []),
                      "mirror": p.get("mirror", False),
                      "children": normalize_parts(p.get("children", [])),
                      "showModel": p.get("showModel", True),
                      "tw": p.get("texWidth", model.get("texWidth", 64) if isinstance(model, dict) else 64),
                      "th": p.get("texHeight", model.get("texHeight", 64) if isinstance(model, dict) else 64)})
    for c in cubes:
        w, h, d = c.get("dimensions", [0, 0, 0])
        inf = c.get("mcScale", 0) or 0
        off = c.get("offset", [0, 0, 0])
        nodes.append({"rotP": tuple(c.get("position", [0, 0, 0])),
                      "rotA": tuple(c.get("rotation", [0, 0, 0])),
                      "boxes": [{"posX": off[0] - inf, "posY": off[1] - inf, "posZ": off[2] - inf,
                                 "dimX": w + 2 * inf, "dimY": h + 2 * inf, "dimZ": d + 2 * inf,
                                 "texOffX": c.get("txOffset", [0, 0])[0], "texOffY": c.get("txOffset", [0, 0])[1],
                                 "mirror": c.get("txMirror", False)}],
                      "mirror": False,
                      "children": normalize_parts({"cubes": c.get("children", [])}),
                      "showModel": not c.get("hidden", False),
                      "tw": model.get("textureWidth", 64), "th": model.get("textureHeight", 64)})
    return nodes


def walk_nodes(nodes, m, tex, quads):
    for n in nodes:
        pm = mat_mul(m, mat_translate(*n["rotP"]))
        pm = mat_mul(pm, mat_rot("z", n["rotA"][2]))
        pm = mat_mul(pm, mat_rot("y", n["rotA"][1]))
        pm = mat_mul(pm, mat_rot("x", n["rotA"][0]))
        if n["showModel"]:
            for b in n["boxes"]:
                box_quads(dict(b, _part_mirror=n.get("mirror", False)), pm, n["tw"], n["th"], tex, quads)
        walk_nodes(n["children"], pm, tex, quads)


def box_quads(box, m, tw, th, tex, quads):
    ex, ey, ez = box.get("expandX", 0), box.get("expandY", 0), box.get("expandZ", 0)
    x0, y0, z0 = box["posX"] - ex, box["posY"] - ey, box["posZ"] - ez
    x1, y1, z1 = box["posX"] + box["dimX"] + ex, box["posY"] + box["dimY"] + ey, box["posZ"] + box["dimZ"] + ez
    w, h, d = box["dimX"] + 2 * ex, box["dimY"] + 2 * ey, box["dimZ"] + 2 * ez
    u, v = box["texOffX"], box["texOffY"]
    mirror = box.get("mirror", False) or box.get("_part_mirror", False)
    # faces as seen from outside; corners ordered TL, TR, BR, BL to match the uv rect.
    # +z is the face towards the viewer (MC "front"), y grows downward.
    faces = [
        ("-y", [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (u + d, v, w, d)),
        ("+y", [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], (u + d + w, v, w, d)),
        ("-x", [(x0, y1, z1), (x0, y1, z0), (x0, y0, z0), (x0, y0, z1)], (u + d + w, v + d, d, h) if mirror else (u, v + d, d, h)),
        ("+z", [(x1, y1, z1), (x0, y1, z1), (x0, y0, z1), (x1, y0, z1)], (u + d, v + d, w, h)),
        ("+x", [(x1, y1, z1), (x1, y1, z0), (x1, y0, z0), (x1, y0, z1)], (u, v + d, d, h) if mirror else (u + d + w, v + d, d, h)),
        ("-z", [(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)], (u + 2 * d + w, v + d, w, h)),
    ]
    for _name, corners, rect in faces:
        quads.append(([apply(m, c) for c in corners], rect, tw, th, tex))


def drop_overlay_boxes(nodes):
    """Vanilla skins duplicate parts as inflated 'hat/overlay' shells (cube + cube_ol).
    In still previews the shell just paints its dithered texture over the base box
    (painter's algorithm), so drop any box whose bounds duplicate an earlier box's."""
    boxes = []
    def collect(ns):
        for n in ns:
            boxes.extend(n["boxes"])
            collect(n["children"])
    collect(nodes)
    skip = set()
    for i, b in enumerate(boxes):
        for j in range(i):
            o = boxes[j]
            if id(b) in skip or id(o) in skip:
                continue
            def eff(bb, a):
                return bb["dim" + a] + 2 * bb.get("expand" + a, 0)
            if all(abs(b[k] - o[k]) < 1.6 for k in ("posX", "posY", "posZ"))                and all(eff(b, a) >= eff(o, a) - 0.4 for a in "XYZ")                and any(eff(b, a) > eff(o, a) + 0.1 for a in "XYZ"):
                skip.add(id(b))
                break
    def apply(ns):
        out = []
        for n in ns:
            n = dict(n, boxes=[b for b in n["boxes"] if id(b) not in skip])
            n["children"] = apply(n["children"])
            out.append(n)
        return out
    return apply(nodes)


def paint_quad(img, pix, rect, tex):
    ux, uy, uw, uh = rect
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    x0, y0 = min(xs), min(ys)
    w = max(1, int(math.ceil(max(xs) - x0)))
    h = max(1, int(math.ceil(max(ys) - y0)))
    # PIL QUAD data = source corners NW, SW, SE, NE; pix order is TL, TR, BR, BL
    data = (ux, uy, ux, uy + uh, ux + uw, uy + uh, ux + uw, uy)
    patch = tex.transform((w, h), Image.QUAD, data, Image.NEAREST)
    img.alpha_composite(patch, (int(round(x0)), int(round(y0))))


def render_world(quads, height=136, pad=4):
    """Bounds + paint a shared list of quads: (pts, uvrect, texw, texh, texture)."""
    if not quads:
        return None
    pts = [p for q in quads for p in q[0]]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    sc = (height - 2 * pad) / max(1e-6, (maxy - miny))
    margin = 400  # room for coordinates outside the final crop
    W = int(math.ceil((maxx - minx) * sc)) + 2 * pad + 2 * margin
    H = height + 2 * margin
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for q in sorted(quads, key=lambda q: sum(p[2] for p in q[0]) / 4):  # far (small z) first, near (+z viewer) last
        pix = [((p[0] - minx) * sc + pad + margin, (p[1] - miny) * sc + pad + margin) for p in q[0]]  # y grows down
        ux, uy, uw, uh = q[1]
        tex = q[4]
        kx, ky = tex.width / max(1.0, q[2]), tex.height / max(1.0, q[3])
        paint_quad(img, pix, (ux * kx, uy * ky, uw * kx, uh * ky), tex)
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else None


# ---------- renderer JS parsing ----------
def resolve_tex(zf, ns, tex_ref):
    """'tgheroes:avengers/hulk/hulk_model' -> Image, from the pack's hero textures."""
    if not tex_ref or ":" not in tex_ref:
        return None
    tns, name = tex_ref.split(":", 1)
    tns = tns or ns
    if name.endswith(".tx.json") or name.startswith("null"):
        return None
    p = f"assets/{tns}/textures/heroes/{name}.png"
    try:
        return Image.open(io.BytesIO(zf.read(p))).convert("RGBA")
    except KeyError:
        return None


def find_tbl(zf, ns, ref):
    """'ns:name' -> path of a matching .tbl anywhere under assets/<ns>/models/."""
    if ":" in ref:
        rns, rn = ref.split(":", 1)
        rns = rns or ns
    else:
        rns, rn = ns, ref
    needle = rn.rsplit("/", 1)[-1]
    hits = [n for n in zf.namelist()
            if n.startswith(f"assets/{rns}/models/") and n.endswith(".tbl") and needle in n]
    if not hits:
        return None
    # prefer an exact basename match, then the smallest file (main parts beat *_variants)
    exact = [n for n in hits if n.rsplit("/", 1)[-1].rsplit(".", 1)[0] == needle]
    return (exact or sorted(hits, key=lambda n: zf.getinfo(n).file_size))[0]


def parse_effects(zf, ns, js):
    """Extract model effects from renderer JS: var -> {tbl, texture, anchor, offset, scale}.

    Patterns seen in the wild:
      var e = renderer.createEffect("fiskheroes:model"); e.setModel(utils.createModel(renderer, "ns:m", "texKey", null));
      var r = renderer.createResource("MODEL", "ns:m"); r.texture.set("texKey");
      e = renderer.createEffect("fiskheroes:model").setModel(r);  // or e.setModel(r);
    A space between the method name and "(" is legal and common (setOffset (…)).
    """
    load = re.search(r"loadTextures\(\{(.*?)\}\)", js, re.S)
    texmap = dict(re.findall(r'"(\w+)"\s*:\s*"([\w:./-]+)"', load.group(1))) if load else {}
    fx = collections.OrderedDict()
    resources = {}

    def register(var, ref, texkey=None):
        if not var or not ref:
            return
        e = fx.setdefault(var, {"ref": ref})
        if texkey and texkey.strip('"') not in ("", "null"):
            e["texkey"] = texkey.strip('"')

    for m in re.finditer(r'(\w+)\s*=\s*renderer\.createResource\(\s*"MODEL"\s*,\s*"([\w:./-]+)"', js):
        resources[m.group(1)] = {"ref": m.group(2)}
    for m in re.finditer(r'(\w+)\.texture\.set\(\s*"(\w+)"\s*\)', js):
        if m.group(1) in resources:
            resources[m.group(1)]["texkey"] = m.group(2)

    # chained: var = renderer.createEffect("fiskheroes:model").setModel(...)
    for m in re.finditer(
            r'(\w+)\s*=\s*renderer\.createEffect\("fiskheroes:model"\)\.setModel\(\s*'
            r'(?:utils\.)?createModel\(\s*\w+\s*,\s*"([\w:./-]+)"\s*(?:,\s*"([^"]*)")?[^)]*\)', js):
        register(m.group(1), m.group(2), m.group(3))
    for m in re.finditer(
            r'(\w+)\s*=\s*renderer\.createEffect\("fiskheroes:model"\)\.setModel\(\s*(\w+)\s*\)', js):
        if m.group(2) in resources:
            r = resources[m.group(2)]
            register(m.group(1), r["ref"], r.get("texkey"))
    # plain: var.setModel(...)
    for m in re.finditer(
            r'(\w+)\.setModel\(\s*(?:utils\.)?createModel\(\s*\w+\s*,\s*"([\w:./-]+)"\s*(?:,\s*"([^"]*)")?[^)]*\)', js):
        register(m.group(1), m.group(2), m.group(3))
    for m in re.finditer(r'(\w+)\.setModel\(\s*(\w+)\s*\)', js):
        if m.group(2) in resources:
            r = resources[m.group(2)]
            register(m.group(1), r["ref"], r.get("texkey"))

    # anchors / offsets / scales
    for var, e in fx.items():
        am = re.search(re.escape(var) + r'\.anchor\.set\(\s*"(\w+)"', js)
        e["anchor"] = am.group(1) if am else "root"
        om = re.search(re.escape(var) + r'\.setOffset\s*\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)', js)
        e["offset"] = tuple(float(g) for g in om.groups()) if om else (0.0, 0.0, 0.0)
        sm = re.search(re.escape(var) + r'\.setScale\s*\(\s*([\d.]+)\s*\)', js)
        if sm:
            e["scale"] = float(sm.group(1))

    # resolve refs -> tbl paths + textures
    resolved = []
    for var, e in fx.items():
        tbl = find_tbl(zf, ns, e["ref"])
        if not tbl:
            continue
        tex = resolve_tex(zf, ns, texmap[e["texkey"]]) if "texkey" in e and e["texkey"] in texmap else None
        resolved.append({"var": var, "tbl": tbl, "tex": tex, **e})
    return resolved


def effects_with_parents(zf, ns, js, depth=3):
    """parse_effects on js; if empty, chase extend("ns:parent") and use the parent's
    model effects (child renderers often only add props on top of the parent's body)."""
    effects = parse_effects(zf, ns, js)
    if effects or depth == 0:
        return effects
    m = re.search(r'extend\(\s*"([\w:.-]+)"', js)
    if not m:
        return effects
    ref = m.group(1)
    pns, pname = (ref.split(":", 1) + [""])[:2] if ":" in ref else (ns, ref)
    pfile = f"assets/{pns or ns}/renderers/heroes/{pname}.js"
    try:
        pjs = zf.read(pfile).decode("utf-8", errors="replace")
    except KeyError:
        return effects
    return effects_with_parents(zf, pns or ns, pjs, depth - 1)


def render_hero(zf, ns, hid, js):
    """Returns (PIL.Image, None) or (None, skip reason).

    Two composition modes are tried in order: "identity" renders every model in its own
    authored coordinates (works when a character is split into part files sharing one
    origin — the common case); "anchors" re-rigs each effect onto ModelBiped slots using
    the JS anchor/offset/scale values (for parts authored locally). The first mode whose
    result passes the sanity gates wins."""
    effects = effects_with_parents(zf, ns, js)
    if not effects:
        return None, "no usable .tbl model effects"
    forced = OVERRIDES.get(f"{ns}:{hid}")
    if forced is not None and not forced:
        return None, "overridden: no model preview by design"
    if forced:
        if isinstance(forced, dict):
            prefixes = tuple(forced.get("vars", []))
            kept = [e for e in effects if e["var"].startswith(prefixes)] if prefixes else []
        else:
            needles = set(forced)
            kept = [e for e in effects if any(nd in e["tbl"] for nd in needles)]
        if kept:
            effects = kept
    effects = effects[:MAX_EFFECTS]

    loaded = []
    for e in effects:
        try:
            model, inner_tex = load_tbl(zf, e["tbl"])
        except Exception as ex:
            return None, f"render error: {ex}"
        tex = e.get("tex") or inner_tex
        if tex is None:
            continue
        loaded.append((e, normalize_parts(model), tex))
    if not loaded:
        return None, "no renderable geometry/textures"

    def build(mode):
        quads = []
        for e, nodes, tex in loaded:
            nodes = drop_overlay_boxes(nodes)
            base = mat_identity()
            if mode == "anchors":
                a = ANCHORS.get(e["anchor"], (0, 0, 0))
                off = e.get("offset", (0, 0, 0))
                base = mat_translate(a[0] + off[0], a[1] + off[1], a[2] + off[2])
                s = e.get("scale", 1.0)
                if s != 1.0:
                    base = mat_mul(base, mat_scale(s))
            walk_nodes(nodes, base, tex, quads)
        return render_world(quads)

    def gates(img):
        if img is None:
            return "empty render", None
        if img.width * img.height < MIN_PIXELS:
            return f"too small ({img.width}x{img.height})", None
        if img.width / max(1, img.height) > MAX_W_H_RATIO:
            return f"scene-like aspect ({img.width}x{img.height})", None
        return None, img

    def spread(img):
        """union width vs the widest single model -> how far apart the parts landed"""
        widest = 1
        for _e, nodes, tex in loaded:
            qs = []
            walk_nodes(nodes, mat_identity(), tex, qs)
            pts = [p for q in qs for p in q[0]]
            if pts:
                widest = max(widest, max(p[0] for p in pts) - min(p[0] for p in pts))
        return img.width / widest

    results = {}
    notes = {}
    for mode in ("identity", "anchors"):
        note, img = gates(build(mode))
        notes[mode] = note
        if img is not None:
            results[mode] = (spread(img), img)
    if results:
        best = min(results, key=lambda m: results[m][0])
        return results[best][1], None
    return None, " / ".join(n for n in notes.values() if n)


def register_sources(mc_root):
    packs = mc_root / "versions/SuperHERO/fiskheroes"
    sources = {}

    def add(zpath):
        zf = zipfile.ZipFile(zpath)
        for n in zf.namelist():
            m = re.match(r"^assets/([a-z0-9_]+)/data/heroes/", n)
            if m:
                sources.setdefault(m.group(1), zf)

    for z in sorted(packs.glob("*.zip")):
        add(z)
    marketplace = packs / ".marketplace"
    if marketplace.is_dir():
        for z in sorted(marketplace.glob("*.zip")):
            add(z)
    return sources


def make_sheet(rendered, repo, sheet_path):
    per_row, TW, TH, LH = 10, 76, 150, 12
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    rows = (len(rendered) + per_row - 1) // per_row
    sheet = Image.new("RGB", (per_row * TW, max(1, rows) * (TH + LH)), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    for i, hid in enumerate(rendered):
        im = Image.open(repo / "assets" / "heroes" / "models" / f"{hid.replace(':', '__')}.png").convert("RGBA")
        im.thumbnail((TW - 4, TH - 4))
        x, y = (i % per_row) * TW, (i // per_row) * (TH + LH)
        sheet.paste(im, (x + (TW - im.width) // 2, y + (TH - im.height) // 2), im)
        d.text((x + 2, y + TH), hid.split(":")[-1][:15], fill=(220, 220, 220))
    sheet.save(sheet_path)
    print("sheet:", sheet_path)


def main():
    args = parse_args()
    out = args.repo / "assets" / "heroes" / "models"
    out.mkdir(parents=True, exist_ok=True)
    sources = register_sources(args.mc_root)
    heroes = json.load(open(args.repo / "heroes_list.json", encoding="utf-8"))

    sample = set(args.sample.split(",")) if args.sample else None
    stats = collections.Counter()
    rendered, skipped = [], []
    for ns, pack in heroes["packs"].items():
        zf = sources.get(ns)
        if zf is None:
            continue
        names = set(zf.namelist())
        for h in pack["heroes"]:
            hid = h["id"].split(":", 1)[1]
            if sample and h["id"] not in sample:
                continue
            if (h.get("image_game") or h.get("image_wiki")) and not sample:
                continue  # covered by the texture composer / wiki render already
            rfile = f"assets/{ns}/renderers/heroes/{hid}.js"
            if rfile not in names:
                continue
            js = zf.read(rfile).decode("utf-8", errors="replace")
            try:
                img, note = render_hero(zf, ns, hid, js)
            except Exception as e:
                img, note = None, f"error: {e}"
            if img is None:
                skipped.append((h["id"], note))
                continue
            img.save(out / f"{ns}__{hid}.png")
            stats[ns] += 1
            rendered.append(h["id"])

    print(f"rendered {len(rendered)} model previews -> {out.relative_to(args.repo)}/")
    for ns, c in stats.most_common():
        print(f"  {ns:20s} {c}")
    print(f"skipped {len(skipped)}:")
    for hid, why in skipped:
        print(f"  - {hid}: {why}")

    if args.sheet and rendered:
        make_sheet(rendered, args.repo, args.sheet)


if __name__ == "__main__":
    main()
