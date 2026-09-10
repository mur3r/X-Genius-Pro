# X-Genius

Бот массовой рассылки в групповые чаты X (Twitter) через Selenium + Chrome. Интерфейс — локальная
веб-страница (aiohttp), открывается автоматически в окне Chrome без адресной строки.
Windows-only (пути `Bro/chrome.exe`, `Drivers/chromedriver.exe`).

## Запуск

### 1. Что нужно

- Windows, Python 3.9+ (при установке Python отметьте «Add python.exe to PATH»).
- Базовая папка (например `C:\SoftTwitter`), в которой лежат `Bro\chrome.exe` и `Drivers\chromedriver.exe`
  (версии Chrome и chromedriver должны совпадать).

### 2. Установка зависимостей (один раз)

Откройте консоль (`cmd` или PowerShell) в папке проекта — там, где лежит `main.py`:

```bat
cd C:\path\to\TarasGenius
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Виртуальное окружение (`.venv`) необязательно, но так зависимости не смешиваются с системным Python.
Если `python` не находится, используйте `py` вместо `python`.

### 3. Запуск `main.py`

```bat
cd C:\path\to\TarasGenius
.venv\Scripts\activate
python main.py
```

Запускать нужно именно из папки проекта (рядом с `main.py` и папкой `xgenius/`). В консоли появится строка:

```
X-Genius 2026.09 web UI: http://127.0.0.1:8765/
```

**Не закрывайте это окно консоли** — это и есть сервер программы: пока оно открыто, работают логины и
рассылка. Сюда же выводятся служебные сообщения и ошибки запуска.

При первом запуске откроется экран **Setup**: укажите базовую папку (например `C:\SoftTwitter`).
Путь сохраняется в `paths.json`, при следующих запусках Setup уже не показывается. В базовой папке
появятся `accounts.json`, `browser_profiles/`, `logs/` и остальные данные.
Проверка лицензионного ключа отключена (модуль `xgenius/license.py` оставлен, но не подключён).

### 4. Как открыть интерфейс в браузере

- **Автоматически.** После старта интерфейс открывается сам: если в базовой папке найден `Bro\chrome.exe` —
  отдельным окном Chrome без адресной строки (профиль этого окна хранится в `<базовая папка>\webui_profile`),
  иначе — во вкладке браузера по умолчанию. При самом первом запуске (базовая папка ещё не выбрана)
  открывается браузер по умолчанию.
- **Вручную.** Откройте в любом браузере на том же компьютере (внутри той же RDP-сессии):
  **http://127.0.0.1:8765** — страница сама перейдёт на `/static/index.html`.
- **Окно интерфейса можно закрыть** — программа продолжит работать, пока открыта консоль. Чтобы вернуться,
  снова откройте http://127.0.0.1:8765. Можно держать несколько вкладок одновременно.
- **Консоль (лог) в интерфейсе** — панель **Monitor** внизу страницы: живой лог всех аккаунтов,
  фильтр по `@user` или тексту, копирование. Если страница ведёт себя странно, откройте инструменты
  разработчика браузера (`F12` или `Ctrl+Shift+I`, вкладка **Console**) — там видны ошибки JavaScript
  и обрывы WebSocket.
- Статус соединения показан вверху справа. Если сервер недоступен, страница показывает демо-данные
  с жёлтой плашкой «Demo data» и сама переключится на живые, когда сервер поднимется.

### 5. Остановка

Кнопка **Exit** вверху справа (закрывает все браузеры аккаунтов и завершает программу) или `Ctrl+C`
в окне консоли. В обоих случаях при выходе принудительно закрываются оставшиеся процессы `chromedriver`.

### 6. Настройки запуска

Секреты и константы тюнинга: скопируйте `config/settings.example.json` в `config/settings.json`
и поправьте значения. Любой ключ ЗАГЛАВНЫМИ буквами переопределяет константу из `xgenius/settings.py`.
Для веб-интерфейса:

| Ключ | По умолчанию | Что делает |
|---|---|---|
| `WEB_PORT` | `8765` | порт интерфейса; поменяйте, если 8765 занят (тогда адрес `http://127.0.0.1:<порт>`) |
| `WEB_HOST` | `"127.0.0.1"` | адрес, на котором слушает сервер; только локальный доступ |
| `OPEN_BROWSER` | `true` | `false` — не открывать интерфейс при старте, только адрес в консоли |
| `BROWSER_APP_MODE` | `true` | `false` — открывать обычной вкладкой вместо окна без адресной строки |

Пример `config/settings.json`, если нужен другой порт и обычная вкладка:

```json
{ "WEB_PORT": 8800, "BROWSER_APP_MODE": false }
```

Если при старте в консоли ошибка вида `address already in use` / `10048` — программа уже запущена
(или порт занят чем-то другим): закройте старое окно консоли либо поменяйте `WEB_PORT`.

### Тесты

Тесты чистой логики (без selenium):

```bash
python -m unittest discover -s tests -v
```

## Интерфейс

- Верхняя панель: базовая папка, состояние соединения, тема, справка, выход. Под ней — сводка: Accounts / Ready / Mailing / Errors / Inactive / Sent / Groups.
- Панель действий — те же операции, что были в tkinter: Login, Close, Pause/Resume, Reset errors, Close all;
  Start selected, Start all ready, Parse groups; Add, Import, Bulk edit, Mass messages, Export chats, Delete; History.
- Таблица аккаунтов с поиском, фильтром по группе и статусу; в строке — Login, View, Parse, Mail,
  Pause/Resume, Settings, Comments, Edit, 24h stats, Close, Delete.
- Monitor — живой лог внизу (фильтр по `@user` или тексту, копирование).
- Состояние и логи приходят по WebSocket; при разрыве соединения страница переподключается сама.
- Если сервис недоступен, страница показывает демо-данные с жёлтой плашкой «Demo data» и переключается на живые,
  как только сервис поднимется. Посмотреть дизайн без сервиса: открыть `xgenius/web/static/preview.html`
  (одностраничная сборка со встроенными CSS/JS; пересобирается командой `python tools/build_preview.py`).

## Структура проекта

```
main.py                     точка входа (вызывает xgenius.app.run)
human1.py                   Humanizer: параметры "человеческого" набора (не трогаем)
requirements.txt
config/settings.example.json
tests/test_core.py          юнит-тесты xgenius/core
ANALYSIS.md                 разбор проблем по ТЗ клиента и что изменено

xgenius/
  __init__.py               подавление предупреждений urllib3/asyncio
  app.py                    run() -> xgenius.web.server.serve()
  settings.py               константы тюнинга, веб/Telegram/Google, override из config/settings.json
  models.py                 dataclass'ы: AccountState, AccountCredentials, CycleSettings, ...
  config.py                 Config: базовая папка (paths.json) и пути к файлам состояния
  logger.py                 Logger: файл + кольцевой буфер для Monitor
  stats.py                  StatsManager: статистика сообщений/ретвитов/комментариев
  managers.py               MessageManager / CycleManager / CommentManager (настройки на аккаунт)
  browser.py                BrowserManager: создание Chrome, флаги, прокси, CDP-блокировка медиа
  cookies.py                куки аккаунта (файл + БД), лог logstest
  process_utils.py          hard_close_browser, kill_orphan_chrome, force_kill_chromedrivers
  license.py                verify_license (Google-таблица)
  text_utils.py             уникализация текста, emoji, leetspeak, экранирование
  telegram_utils.py         safe_send_message и др. (для Telegram-бота)
  database.py               DatabaseManager (SQLite мониторинга для Telegram-бота)
  scheduler.py              TaskScheduler: цикл рассылки, очередь групп, восстановление браузера

  core/                     чистая логика, без selenium (покрыта тестами)
    page_state.py           статусы, JS-зонды, classify_page, classify_driver_error
    chat_store.py           ChatStore: кеш/очередь/страйки/отключённые группы
    typing_split.py         split_for_typing: BMP-символы клавишами, emoji через CDP

  accounts/                 AccountManager = manager.py + миксины
    manager.py              состояние аккаунтов, файлы, токены, экспорт чатов
    health.py               HealthMixin: health-check, watchdog, статус авторизации, блокировки
    auth.py                 AuthMixin: вход (куки → токены → пароль), автоперелогин

  twitter/                  TwitterOperations = operations.py + миксины
    operations.py           сбор групп iChat, цели для ретвитов
    messaging.py            MessagingMixin: send_message, набор текста, кнопка Send, GIF
    social.py               SocialMixin: комментарии и ретвиты
    common.py               accept_cookies, подсчёт подписчиков

  web/                      веб-интерфейс (замена tkinter)
    engine.py               Engine: сборка менеджеров, снимок состояния для UI, логи
    actions.py              операции для API: логин, парсинг, рассылка, настройки, статистика
    server.py               aiohttp: JSON API, WebSocket, статика, запуск и открытие окна
    static/index.html       страница
    static/style.css        стили (тёмная/светлая тема)
    static/icons.js         SVG-иконки
    static/app.js           состояние, WebSocket, сводка, таблица, консоль, действия панели
    static/dialogs.js       модальные окна: аккаунт, импорт, bulk edit, настройки, комментарии, история
    static/help.txt         текст справки
```

Большие классы (`AccountManager`, `TwitterOperations`) разнесены по файлам через миксины:
методы не переименованы, вызовы `self.method()` не менялись.

## Как это работает (коротко)

1. **Login** открывает Chrome с профилем аккаунта (`browser_profiles/profile_<user>`), входит по
   сессии профиля → кукам → токенам → паролю (`accounts/auth.py`).
2. **Mailing** запускает `TaskScheduler.start_sending_cycle`: парсит группы из iChat, объединяет
   с кешем (`core/chat_store.py`), затем по очереди отправляет сообщения (`twitter/messaging.py`).
3. Перед набором текста страница чата опрашивается JS-зондом и классифицируется
   (`core/page_state.py`): поле ввода есть → печатаем; чат загружен без поля → страйк группе
   (после 3 — отключение на 24 ч, из кеша не удаляется); временная ошибка → группа в конец очереди.
4. Если браузер умер или сессия потеряна — `_recover_browser` закрывает Chrome принудительно,
   открывает новый, входит заново и продолжает ту же очередь.
5. Файлы состояния групп в рабочей папке: `chat_cache.json`, `chat_queue.json`, `chat_state.json`.

Подробный разбор проблем и решений — в `ANALYSIS.md`.

## API (для интеграций)

`GET /api/state`, `WS /ws` (state + logs), `POST /api/setup`,
`POST /api/accounts`, `POST /api/accounts/import`, `GET|PUT /api/accounts/{u}`, `POST /api/accounts/delete`,
`POST /api/accounts/bulk_edit`, `GET|PUT /api/accounts/{u}/settings`, `POST /api/settings/mass`,
`GET|PUT /api/accounts/{u}/comments`, `POST /api/actions/{login|parse|mailing|pause|close|view|reset_errors|clear_groups|export_chats}`,
`GET /api/stats/daily/{u}`, `GET /api/stats/history[.csv]?from=&to=`, `DELETE /api/stats/{u}`, `POST /api/shutdown`.

## Известные ограничения

- `TelegramBotManager` в исходниках отсутствует: всё, что связано с Telegram-ботом, не активно
  (программа пишет об этом предупреждение в лог).
- Сервер слушает только `127.0.0.1`. Для доступа с другого ПК задайте `WEB_HOST` и защитите доступ
  (VPN/файрвол) — авторизации в интерфейсе нет.
- Токен бота и лог `logstest` с паролями/токенами — см. раздел «Безопасность» в `ANALYSIS.md`.
