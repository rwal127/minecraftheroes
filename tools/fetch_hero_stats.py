# Builds stats.json: per-hero gameplay data mined from the local game install —
# data/heroes/*.js inside the mod jar (67 built-ins) and every heropack zip
# (the rest). Extracts tier, ability labels (key.* codes resolved through the
# mod's en_US.lang) and trait flags derived from attribute modifiers. The UI
# composes these into localized template descriptions, so no wiki text is
# needed and every hero gets one.
#
# Variant heroes often delegate to a shared base ("sind:external/iron_man_base"
# -> data/heroes/external/iron_man_base.js): tier may arrive as the first
# argument of base.init(hero, N, ...) and abilities/attributes may live in the
# base file, so base files are parsed and merged too. A few packs obfuscate
# their JS with \xNN hex escapes — those are unescaped before parsing.
#
# Usage:
#   python tools/fetch_hero_stats.py --mc-root "C:\Games\Minecraft" [--repo PATH]
import argparse
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

JAR_GLOB = "FiskHeroes-*.jar"

# Runs a hero definition in node with a recording stub instead of the real mod:
# a couple of packs obfuscate hero JS with rotated string tables + decoder
# functions that regexes can't see through, but the code itself still just
# calls hero.setTier / addKeyBind / addAttribute at init time.
NODE_HARNESS = r'''
const fs = require("fs");
const src = fs.readFileSync(0, "utf8");
const rec = {tier: null, abilities: [], attrs: {}};
const base = {
  setTier(n) { rec.tier = n; },
  addKeyBind(k, label, slot) { rec.abilities.push([slot ?? 99, String(label)]); },
  addKeyBindFunc(fn, f, label, slot) { rec.abilities.push([slot ?? 99, String(label)]); },
  addAttribute(k, v, op) { if (op === 0) rec.attrs[k] = Math.max(rec.attrs[k] || 0, v); },
};
const stub = () => new Proxy(base, {get: (t, p) => (p in t ? t[p] : () => undefined)});
global.implement = (ref) => new Proxy({}, {get: (t, p) => (...args) => {
  if (p === "init" && typeof args[1] === "number" && rec.tier === null) rec.tier = args[1];
  return undefined;
}});
try {
  new Function("hero", "implement", src + "\n;init(hero, implement);")(stub(), global.implement);
  console.log(JSON.stringify(rec));
} catch (e) {
  console.log(JSON.stringify({tier: null, abilities: [], attrs: {}, error: String(e)}));
}
'''

# trait flags derived from flat (op=0) attribute modifiers; (attribute, min value)
TRAIT_RULES = [
    ("t_melee", [("PUNCH_DAMAGE", 4.0), ("WEAPON_DAMAGE", 4.0)]),
    ("t_speed", [("SPRINT_SPEED", 0.1), ("BASE_SPEED", 0.1), ("BASE_SPEED_LEVELS", 1.0)]),
    ("t_tank", [("FALL_RESISTANCE", 3.0), ("MAX_HEALTH", 6.0)]),
    ("t_jump", [("JUMP_HEIGHT", 2.0)]),
    ("t_archery", [("BOW_DRAWBACK", 0.0)]),
]

MAX_ABILITIES = 10


def unescape_js(text: str) -> str:
    r"""Turn \xNN hex escapes (obfuscated packs) back into characters."""
    if "\\x" not in text:
        return text
    return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)


def deobfuscate(text: str) -> str:
    """Undo string-table obfuscation: var _0xABCD=["lit",...] makes every
    method name and string literal an indexed lookup (_0xABCD[5])."""
    m = re.search(r"var\s+(_0x\w+)\s*=\s*(\[.*?\])\s*;", text, re.S)
    if not m:
        return text
    try:
        table = json.loads(m.group(2))
    except ValueError:
        return text
    name, table = m.group(1), [str(x) for x in table]
    text = re.sub(name + r"\[(\d+)\]",
                  lambda mo: json.dumps(table[int(mo.group(1))]) if int(mo.group(1)) < len(table) else mo.group(0),
                  text)
    # obj["setTier"](10) -> obj.setTier(10)
    return re.sub(r'\[("([^"\\]|\\.)*")\]\(', lambda m: "." + json.loads(m.group(1)) + "(", text)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def call_args(text: str, start: int) -> tuple[str, int]:
    """Given index of '(' return the argument substring and index after ')'."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return text[start + 1:], len(text)


def quoted(args: str) -> list[str]:
    return re.findall(r'"((?:[^"\\]|\\.)*)"', args)


def parse_hero_js(text: str) -> dict:
    """Pull tier / abilities / attributes out of one hero definition file."""
    text = deobfuscate(strip_comments(unescape_js(text)))
    out = {"tier": None, "abilities": [], "attrs": {}}
    hero = r"(?:hero|_0x\w+)\."  # plain files use the hero param, obfuscated keep _0x names

    m = re.search(hero + r"setTier\(\s*(\d+)", text) or re.search(r"\.init\(\s*hero\s*,\s*(\d+)", text)
    if m:
        out["tier"] = int(m.group(1))

    for name in ("addKeyBind", "addKeyBindFunc"):
        for m in re.finditer(name + r"\s*\(", text):
            args, _ = call_args(text, m.end() - 1)
            qs = quoted(args)
            if not qs:
                continue
            slot_m = re.search(r",\s*(\d+)\s*$", args)
            slot = int(slot_m.group(1)) if slot_m else 99
            out["abilities"].append((slot, qs[-1]))

    for m in re.finditer(hero + r"addAttribute\(\s*\"(\w+)\"\s*,\s*(-?[\d.]+)\s*,\s*(\d+)\s*\)", text):
        key, val, op = m.group(1), float(m.group(2)), int(m.group(3))
        if op == 0:  # flat adds only: multiply semantics vary, not safe to present
            out["attrs"][key] = max(out["attrs"].get(key, 0.0), val)

    return out


def interpret_js_escapes(s: str) -> str:
    r"""The regex parser sees raw \uXXXX / \xNN sequences inside JS strings —
    turn them into characters (color codes are stripped separately)."""
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return s.replace("\\n", " ").replace("\\t", " ")


def resolve_label(label: str, lang: dict) -> str:
    label = interpret_js_escapes(label)
    label = re.sub(r"[\u00a7&][0-9a-fk-orA-FK-OR]", "", label)  # MC color codes
    if label.startswith("key."):
        label = lang.get(label) or label
    label = label.strip()
    if label.startswith("key."):  # pack-specific code missing from the mod lang
        words = re.sub(r"(?<!^)(?=[A-Z])", " ", label[4:]).split("_")
        label = " ".join(w[:1].upper() + w[1:] for w in words)
    return label


def parse_with_node(raw_text: str) -> dict | None:
    """Evaluate a decoder-obfuscated hero file in node; None when not needed."""
    if not re.search(r"_0x\w+\(\s*0x", raw_text) or not raw_text.strip().startswith("var _0x"):
        return None
    try:
        r = subprocess.run(["node", "-e", NODE_HARNESS], input=raw_text,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        rec = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return {"tier": rec.get("tier"),
            "abilities": [(s, l) for s, l in rec.get("abilities", [])],
            "attrs": {k: float(v) for k, v in rec.get("attrs", {}).items()}}


def base_files(text: str, ns: str, zread) -> list[str]:
    """JS sources of external bases the hero implements ("ns:external/name")."""
    files = []
    for ref in re.findall(r"implement\(\s*\"([\w:/]+)\"\s*\)", unescape_js(text)):
        parts = ref.split(":", 1)
        if len(parts) != 2:
            continue
        path = f"assets/{parts[0]}/data/heroes/{parts[1].replace('.', '/')}.js"
        try:
            files.append(zread(path))
        except KeyError:
            continue
    return files


def main(repo: Path = REPO, mc_root: Path | None = None) -> None:
    if mc_root is None:
        raise SystemExit("mc_root required: pass --mc-root or set MC_ROOT")

    catalog = json.load(open(repo / "heroes_list.json", encoding="utf-8"))
    packs = catalog["packs"]

    hero_root = mc_root / "versions" / "SuperHERO"
    jars = sorted((hero_root / "mods").glob(JAR_GLOB))
    if not jars:
        raise SystemExit(f"no {JAR_GLOB} under {hero_root/'mods'}")
    jar = zipfile.ZipFile(jars[0])

    lang = {}
    for line in jar.read("assets/fiskheroes/lang/en_US.lang").decode("utf-8", "ignore").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            lang[k.strip()] = v.strip()

    # pack namespace -> open zip, matched by the catalog's declared sources
    zips: dict[str, zipfile.ZipFile] = {}
    packs_dir = hero_root / "fiskheroes"
    candidates = list(packs_dir.glob("*.zip")) + list((packs_dir / ".marketplace").glob("*.zip"))
    for ns, p in packs.items():
        if ns == "fiskheroes":
            continue
        for z in candidates:
            if z.name in (p.get("sources") or []):
                zips[ns] = zipfile.ZipFile(z)
                break

    def jar_read(path: str) -> str:
        return jar.read(path).decode("utf-8", "ignore")

    out, no_tier, no_abilities = {}, [], []
    for ns, p in packs.items():
        for h in p["heroes"]:
            hid = h["id"].split(":", 1)[1]
            zread = (lambda path: jar_read(path)) if ns == "fiskheroes" else (
                lambda path, z=zips[ns]: z.read(path).decode("utf-8", "ignore"))
            own_path = f"assets/{ns}/data/heroes/{hid}.js"
            try:
                raw = zread(own_path)
                own = parse_hero_js(raw)
            except KeyError:
                print(f"  !! no hero js: {h['id']}")
                continue
            if own["tier"] is None or not own["abilities"]:
                via_node = parse_with_node(raw)  # decoder-obfuscated packs
                if via_node:
                    own["tier"] = own["tier"] if own["tier"] is not None else via_node["tier"]
                    own["abilities"] += via_node["abilities"]
                    for k, v in via_node["attrs"].items():
                        own["attrs"][k] = max(own["attrs"].get(k, 0.0), v)

            tier, abilities, attrs = own["tier"], list(own["abilities"]), dict(own["attrs"])
            for base in base_files(zread(own_path), ns, zread):
                parsed = parse_hero_js(base)
                if tier is None:
                    tier = parsed["tier"]
                abilities += parsed["abilities"]
                for k, v in parsed["attrs"].items():
                    attrs[k] = max(attrs.get(k, 0.0), v)

            seen, labels = set(), []
            for slot, raw in sorted(abilities, key=lambda x: x[0]):
                label = resolve_label(raw, lang)
                # skip menu-arrow keybinds and other labels without any text
                if label and any(c.isalnum() for c in label) and label.lower() not in seen:
                    seen.add(label.lower())
                    labels.append(label)
            traits = [name for name, rules in TRAIT_RULES
                      if any(attrs.get(a, 0.0) >= v for a, v in rules)][:3]

            if tier is None:
                no_tier.append(h["id"])
            if not labels:
                no_abilities.append(h["id"])
            entry = {"tier": tier, "abilities": labels[:MAX_ABILITIES]}
            if traits:
                entry["traits"] = traits
            out[h["id"]] = entry

    (repo / "stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(p["heroes"]) for p in packs.values())
    print(f"stats: {len(out)}/{total} heroes -> stats.json "
          f"(tier: {len(out)-len(no_tier)}, abilities: {len(out)-len(no_abilities)}, "
          f"traits: {sum(1 for v in out.values() if 'traits' in v)})")
    if no_tier:
        print(f"  no tier ({len(no_tier)}): {', '.join(no_tier[:10])}")
    if no_abilities:
        print(f"  no abilities ({len(no_abilities)}): {', '.join(no_abilities[:10])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build stats.json from local game files.")
    ap.add_argument("--mc-root", default=os.environ.get("MC_ROOT"),
                    help="path to the local game install holding the mod jar and heropacks (env: MC_ROOT)")
    ap.add_argument("--repo", type=Path, default=REPO,
                    help=f"catalog repo root (default: {REPO})")
    a = ap.parse_args()
    if not a.mc_root:
        ap.error("--mc-root (or the MC_ROOT env var) is required: path to the game install "
                 "with versions/SuperHERO/mods/ and versions/SuperHERO/fiskheroes/")
    main(repo=a.repo, mc_root=Path(a.mc_root))
