# Скрипты обслуживания каталога

Все инструменты — обычные Python-скрипты без сборки. Зависимости: `requests` и `Pillow` (только для скриптов превью), стандартная библиотека для остальных.

```bash
pip install requests Pillow
```

Общие принципы:

- пути **не зашиты в код**: расположение игры, репозитория и кэшей передаётся параметрами CLI или переменными окружения;
- почти у каждого скрипта есть `--repo` — корень каталога (по умолчанию — тот чекаут, где лежит скрипт);
- скрипты детерминированы: повторный прогон на тех же входных данных даёт побайтово те же файлы.

## Пайплайн превью (порядок важен)

```
1. hero_previews_game.py    → assets/heroes/game/*.png
2. hero_previews_models.py  → assets/heroes/models/*.png
3. wiki_previews.py         → assets/heroes/wiki/*.png + мерж полей в heroes_list.json
4. fetch_descriptions.py    → descriptions.json
5. make_sheets.py           → research/out/sheets/*.png (QA, в git не хранится)
6. tests/validate_data.py   → проверка целостности всего выше
```

---

## tools/hero_previews_game.py — фронтальные превью из текстур

Собирает фронтальный вид каждого костюма (голова + торс + руки + ноги, ×4 NEAREST) из текстур внутри jar мода и херопаков. Читает `models/heroes/*.json` → `renderers/heroes/*.js` с конвенцией `_layer1`; накладывает слои друг на друга.

**Ключевой механизм — гейт качества**: настоящий скин-костюм почти полностью заполняет UV-области торса и конечностей; кастомные Tabula-модели (Hulk, Thanos, MODOK…) оставляют там фрагменты, и такие герои осознанно не получают превью. Голова НЕ проверяется: у героев без шлема она прозрачна намеренно (там рендерится голова игрока). Не возвращайте проверку головы — она отсеет ~100 годных превью.

```bash
python tools/hero_previews_game.py --mc-root "C:\Games\Minecraft"
python tools/hero_previews_game.py --mc-root "C:\Games\Minecraft" the_flash,zoom   # только указанные герои
```

| Параметр | Описание |
|---|---|
| `sample` (позиционный) | необязательный список ID героев через запятую (без неймспейса) — регенерировать только их |
| `--mc-root` | **обязателен** (или env `MC_ROOT`): путь к клиенту игры с `versions/SuperHERO/mods/` и `versions/SuperHERO/fiskheroes/` |
| `--repo` | корень каталога (по умолчанию — текущий чекаут) |

Входы: `versions/SuperHERO/mods/FiskHeroes-1.7.10-2.4.0.jar`, `versions/SuperHERO/fiskheroes/*.zip` (активные паки) и `fiskheroes/.marketplace/*.zip` (неактивные), `heroes_list.json`.
Выходы: `assets/heroes/game/<pack>__<hero>.png`, `research/out/no_texture_heroes.json` (список героев без превью).
Отладка: env `PREVIEW_DEBUG=1` печатает покрытие UV-областей по каждому герою.

## tools/hero_previews_models.py — рендер кастомных Tabula-моделей

Герои, чей костюм — не скин-раскладка, а кастомная геометрия (Hulk, Thanos, MODOK, Hulkbuster…), заданы в херопаках Tabula-файлами (`.tbl` — ZIP с `model.json` кубов и `texture.png`). Скрипт статически парсит JS-рендерер каждого героя, находит все модели-эффекты, их текстуры из `loadTextures` и собирает фронтальный вид софтверным рендером (ортографическая проекция, painter's algorithm, NEAREST) — **без запуска игры**.

Композиция пробуется в двух режимах: «identity» (части уже автораны в общих координатах — типичный случай) и «anchors» (части расставляются по слотам ModelBiped из JS-якорей). Побеждает режим с более компактной композицией; гейты отсекают пустые и «сценовые» рендеры (армии, порталы). Если у рендерера нет своих моделей, эффекты берутся у родителя по `extend()` (Blue Beetle, Ultron Comics, Cloak). Дубли-«шеллы» (cube + cube_ol, hat-слой) выкидываются — иначе они перекрывают лицо дизеринговым паттерном.

```bash
python tools/hero_previews_models.py --mc-root "C:\Games\Minecraft"
python tools/hero_previews_models.py --mc-root "C:\Games\Minecraft" tgheroes:hulk --sheet qa.png  # точечно + контакт-лист
```

| Параметр | Описание |
|---|---|
| `sample` (позиционный) | ID героев через запятую (с неймспейсом) — перерендерить только их |
| `--mc-root` | **обязателен** (или env `MC_ROOT`): путь к клиенту игры с херопаками |
| `--repo` | корень каталога |
| `--sheet` | сохранить QA-контакт-лист отрендеренного по этому пути |

Выход: `assets/heroes/models/<pack>__<hero>.png`. Скрипт рендерит только героев без вики-рендера и без текстурного превью — приоритет источников: вики → модель → текстуры. Спорные случаи правятся таблицей `OVERRIDES` внутри скрипта: список моделей по подстроке имени, `{'vars': [...]}` по имени эффекта либо `[]` — осознанный скип (предметы, скин-герои с обрезками). Пропущенные герои печатаются с причиной.

## tools/wiki_previews.py — вики-рендеры + мерж данных

Докачивает 3D-рендеры встроенных костюмов с fiskheroes.fandom.com (страница → файл превью берётся из кэша ресёрча) и переписывает `heroes_list.json`: поля `image` / `image_wiki` / `image_game` / `wiki` у каждого героя + блок статистики `meta.previews`. Каноническое превью: вики-рендер → рендер Tabula-модели → игровой вид из текстур.

```bash
python tools/wiki_previews.py --mc-root "C:\Games\Minecraft"
python tools/wiki_previews.py --wiki-research "D:\backup\wiki_research" --repo . --redownload
```

| Параметр | Описание |
|---|---|
| `--mc-root` | путь к клиенту игры — нужен только чтобы найти кэш `<mc-root>/wiki_research/` (env `MC_ROOT`) |
| `--wiki-research` | путь к кэшу ресёрча (`allimages.json`, `wiki_pages.json`) напрямую (env `WIKI_RESEARCH`) |
| `--repo` | корень каталога |
| `--redownload` | перекачать рендеры, даже если файлы уже существуют |

Грабли (уже решены в коде, не сломайте):

- CDN static.wikia отдаёт **403 на длинные User-Agent** — работает ровно `Mozilla/5.0`;
- CDN всегда отдаёт **WebP** независимо от Accept — поэтому ответ прогоняется через Pillow и сохраняется в PNG/JPG по расширению;
- серия запросов **рейт-лимитится** — в `download()` есть ретраи с нарастающей паузой;
- имена файлов вики нормализуются (пробелы ↔ подчёркивания) в `fetch_file_url()`;
- страница Savitar — редирект на The Rival (используется прямой файл `Savitar.png`), страница Доктора Октопуса называется «Doctor Octupus» (опечатка вики) — всё зафиксировано в таблице `WIKI_PAGE` внутри скрипта.

Выходы: `assets/heroes/wiki/<hero>.<ext>` (640px по ширине), обновлённый `heroes_list.json`.

## tools/fetch_descriptions.py — описания со страниц костюмов

Обходит страницы встроенных костюмов через MediaWiki API (`action=parse&prop=wikitext`) и собирает то же, что показывает вики: **тир**, **% снижения урона**, **цену в Tutridium**, группы **способностей** и интро-абзац страницы. Из «Powers & Abilities» выкидываются служебные группы `Stats`/`Effects` и стат-буллеты (`* + 85% Damage Reduction` — попадает в поле `dr`, а не в способности).

```bash
python tools/fetch_descriptions.py
python tools/fetch_descriptions.py --refresh   # перекачать wikitext, игнорируя кэш
```

| Параметр | Описание |
|---|---|
| `--repo` | корень каталога (там же берётся `heroes_list.json` для списка встроенных героев) |
| `--refresh` | принудительно перекачать страницы (по умолчанию используется кэш) |

Кэш: `research/out/wiki_suit_pages.json` (gitignored) — повторные прогоны не ходят в сеть. Между запросами пауза 1 с, до 4 ретраев.
Выход: `descriptions.json` — `{hero_id: {tier, dr, cost, powers[], note}}`. Херопак-герои получают шаблонное описание в самом UI (сайт переводит его на язык интерфейса).

## tools/make_sheets.py — QA-контакт-листы

Клеит все канонические превью в пронумерованные листы с подписями — удобно просматривать глазами после перегенерации.

```bash
python tools/make_sheets.py
python tools/make_sheets.py --out "D:\tmp\sheets" --per-sheet 200
```

| Параметр | Описание |
|---|---|
| `--repo` | корень каталога |
| `--out` | папка для листов (по умолчанию `<repo>/research/out/sheets`, gitignored) |
| `--per-sheet` | миниатюр на лист (по умолчанию 100) |

Выход: `sheet_01.png`, `sheet_02.png`, … — не деплоятся, только для визуальной проверки.

## tools/generate_commands.py — список команд /suit

Перегенерирует плоский текстовый список `hero_atlas_commands.txt` из `heroes_list.json` (ссылка на него есть в футере сайта). Названия паков берутся из таблицы `DISPLAY` внутри скрипта.

```bash
python tools/generate_commands.py [--repo PATH]
```

## tools/merge_aliases.py — сборка алиасов поиска

Сливает выдачу субагентов-ресёрчеров `research/out/agent_*.json` в `aliases.json` (`hero_id → [алиасы]`): дубликаты схлопываются, алиасы приводятся к нижнему регистру, ID, которых нет в каталоге, отбрасываются с отчётом. Каждому герою каталога гарантируется запись (возможно, пустая) — это инвариант, который проверяет `tests/validate_data.py`.

```bash
python tools/merge_aliases.py [--repo PATH]
```

## tests/validate_data.py — валидация данных (не деплоится)

Проверяет целостность всего каталога без браузера: точность счётчиков, уникальность и формат ID (`pack:hero`), принадлежность ID своим пакам, отсутствие устаревших полей статусов, существование **и декодируемость** (PIL) всех файлов превью, консистентность `meta.previews`, валидность `aliases.json` и `descriptions.json`. Код выхода ≠ 0 при любой ошибке — удобно для CI.

```bash
python tests/validate_data.py
```

---

## Что НЕ коммитится

- jar мода и херопаки — только на локальной машине (`--mc-root`);
- `research/out/sheets/`, `research/out/wiki_suit_pages.json`, `research/out/no_texture_heroes.json`, `__pycache__/` — gitignored;
- честная перепроверка превью глазами по контакт-листам перед пушем не отменяется.
