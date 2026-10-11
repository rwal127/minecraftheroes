# Деплой Hero Atlas: Cloudflare Pages + Telegram Mini App

Весь сайт — статические файлы в корне репозитория. Сборка не нужна.

## 1. Cloudflare Pages (автоматический деплой из GitHub)

1. Зайти на <https://dash.cloudflare.com> → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Авторизоваться в GitHub и выбрать репозиторий `rwal127/minecraftheroes`.
3. В настройках сборки указать:
   - **Framework preset**: `None`
   - **Build command**: *(пусто)*
   - **Build output directory**: `/`
4. **Save and Deploy**. Через ~30 секунд сайт доступен по адресу вида `https://<project-name>.pages.dev`.
5. Дальше каждый push в ветку `main` автоматически перезаписывает публикацию — обновление каталога это просто коммит нового `heroes_list.json`.

Проверка после первого деплоя: сайт открывается по HTTPS, счётчики показывают актуальные числа из JSON (при замене файла числа меняются сами), поиск находит героев, кнопка копирования показывает тост «Скопировано».

Опционально: свой домен — вкладка **Custom domains** в настройках проекта Pages.

## 2. Telegram Mini App (тот же URL, отдельного приложения не нужно)

1. Открыть <https://t.me/BotFather> → `/mybots` → выбрать бота (или создать нового: `/newbot`).
2. **Bot Settings** → **Menu Button** → **Configure menu button** → отправить боту ссылку сайта (`https://<project-name>.pages.dev`) → задать название кнопки (например, `Hero Atlas`).
3. Альтернатива через команды: `/setmenubutton`.
4. В чате с ботом слева от поля ввода появится кнопка «Menu» — по нажатию сайт откроется как Mini App на весь экран.

**Требования к Mini App** (уже выполнены в коде):

- страница отдаётся по HTTPS — Cloudflare Pages делает это по умолчанию;
- подключён официальный SDK `https://telegram.org/js/telegram-web-app.js`;
- при старте вызываются `Telegram.WebApp.ready()` и `Telegram.WebApp.expand()`;
- копирование работает через Clipboard API с fallback на `document.execCommand('copy')`, потому что в WebView Telegram буфер обмена иногда ограничен.

Для деплоя через **/newapp** (отдельная Web App-кнопка вместо Menu Button) подойдёт тот же URL — два разных приложения делать не нужно.

## 3. Обновление данных после настройки

```bash
# заменить heroes_list.json (новая выгрузка), затем:
python tools/generate_commands.py   # перегенерировать hero_atlas_commands.txt
python tests/validate_data.py       # проверить целостность
git add heroes_list.json hero_atlas_commands.txt
git commit -m "data: update hero catalog"
git push                            # Cloudflare Pages опубликует автоматически
```

## 4. Что НЕ деплоится

Файлы `*.zip` (исходные архивы) игнорируются через `.gitignore` и в публикацию не попадают — в репозитории и на сайте только распакованное содержимое.
