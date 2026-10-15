# Hero Atlas — Minecraft FiskHeroes hero catalog

A static web catalog of every hero and suit from the Minecraft mod **Fisk's Superheroes
(FiskHeroes) 2.4.0** (1.7.10): **535 heroes in 21 packs**. The same codebase works as a
regular website and a **Telegram Mini App**. No backend, no database, no build step;
styling is the **VS Code Dark+** palette.

## Features

- **8 UI languages** (ru, en, uk, es, ko, ja, fr, de); auto-detected, choice remembered.
- **Previews for 501/535 heroes** (all 67 built-in suits), generated offline by the repo
  tools: 56 3D renders, 464 front views composed from suit textures and 37 renders of
  custom Tabula models; heroes with nothing to render get a placeholder.
- **Hero card** (click a row): large preview, pack, tier, damage reduction and Tutridium
  cost for built-in suits, ability chips (localized, English original in the tooltip),
  a translated template description, hero ID and
  a ready `/suit packname:heroname` command with one-click copy; `‹ ›` navigation over the
  filtered list, `Esc` closes.
- **Search** by name, partial name, ID and pack name across all packs, with **aliases**:
  Russian and English names, translit and acronyms (`one punch man` → Saitama,
  `человек-паук` → every Spider-Man).
- **Ability filter** (⚡ icon): a panel listing every ability in the catalog with its hero
  count; ability names are localized into all 8 UI languages via `ability_i18n.json`
  (the English original stays in the tooltip); checkboxes match any selected ability, the
  mini-search understands multilingual aliases, acronyms and the localized names
  themselves, plus reset and a selection counter on the icon. Combines with name
  search and pack tabs.
- **List & gallery views**: a Material-style segmented control in the toolbar flips the
  catalog between the classic list and a card gallery (2 cards per row by default); a second
  segmented control next to it sets 2/3/4 cards per row in gallery mode. Both choices are
  remembered. The pack-chip strip dissolves smoothly under the counter instead of being
  cut off.
- Separate pack browsing (pack tabs + «📦 Packs» button).
- All counters are computed from JSON at runtime — updating the data needs no code changes.

## Repository layout

```
index.html               the whole app (vanilla HTML/CSS/JS, no dependencies, no build)
heroes_list.json         single source of truth: meta + packs.<ns>.{sources, count, heroes}
stats.json               per-hero game data: tier, abilities, traits (parsed from jar/heropacks)
descriptions.json        damage reduction % and Tutridium cost for built-in suits
aliases.json             search aliases per hero (RU/EN/translit/acronyms)
ability_aliases.json     ability-filter aliases (202 abilities, 601 aliases)
ability_i18n.json        localized ability names, 830 abilities × 7 languages (en = the key)
hero_atlas_commands.txt  flat /suit command list
wrangler.toml            Cloudflare config (static assets, git-integration deploy)
assets/heroes/           previews, ~556 PNG ≈ 12 MB:
                         wiki/ 56 3D renders · game/ 464 texture front views · models/ 37 Tabula renders
docs/                    deployment guide + per-script documentation
tools/                   preview/data generation scripts (see docs/scripts/README.md)
research/                alias research inputs/outputs
tests/validate_data.py   data integrity tests
tests.html               in-browser UI test suite
```

## Updating the catalog

The site fetches `heroes_list.json` with no cache, so an update is replacing one file
(keep the exact hero key set: `id, name, image, image_wiki, image_game, image_model, wiki`):

1. Replace `heroes_list.json`.
2. Optionally regenerate the command list: `python tools/generate_commands.py`.
3. Run the data tests: `python tests/validate_data.py` — must pass.
4. Commit to `main` — Cloudflare Workers static assets deploy automatically.

## Regenerating previews and data

Needs a local game client (jar + heropacks are never committed); its location is passed
via `--mc-root` (env `MC_ROOT`), nothing is hardcoded:

```bash
python tools/hero_previews_game.py   --mc-root "C:\Games\Minecraft"  # game/ front views from suit textures
python tools/hero_previews_models.py --mc-root "C:\Games\Minecraft"  # models/ Tabula-model renders
python tools/wiki_previews.py        --mc-root "C:\Games\Minecraft"  # wiki/ renders + merge into heroes_list.json
python tools/fetch_hero_stats.py     --mc-root "C:\Games\Minecraft"  # stats.json: tier/abilities/traits
python tools/fetch_descriptions.py                                   # descriptions.json: dr %, Tutridium cost
python tools/make_sheets.py                                          # QA contact sheets (gitignored)
python tests/validate_data.py                                        # verify integrity
```

Parameters, inputs/outputs and quality gates for every script:
[docs/scripts/README.md](docs/scripts/README.md).

The 34 heroes without a preview are transformation forms (Ben 10 omnitrix shapes), gadget
items (infinity stones, the gauntlet) and effect-only heroes — there is nothing to render;
the quality gates in the generators deliberately reject garbage instead.

## Local development

```bash
python -m http.server 8123    # open http://127.0.0.1:8123 (tests: /tests.html)
```

A static server is required — `file://` cannot fetch the JSON.

## Deployment

Full guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Short version: connect the repo to
Cloudflare (Workers static assets, no framework, output `/`) — every push to `main`
deploys. For the Telegram Mini App, set the site URL as the bot's menu button via
@BotFather (`/setmenubutton`).

## Tests

- `python tests/validate_data.py` — JSON integrity: counters, ID format/uniqueness,
  per-pack counts, preview files exist and decode, aliases/descriptions/stats validity.
- Open [`tests.html`](tests.html) in a browser — runs the UI suite (rendering, filters,
  alias search, ability panel, copy, hero modal, list/gallery views, image loading,
  8-language switching) and prints `PASSED: n/n` in the title.
- Telegram-only behavior (Mini App chrome, keyboard) is checked manually.

## License

MIT — see [LICENSE](LICENSE).
