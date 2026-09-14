"""
Настройки X-Genius: константы тюнинга и внешние параметры (Telegram, Google Sheets).

Значения по умолчанию совпадают с тем, что раньше было захардкожено в main.py.
Файл config/settings.json (образец — config/settings.example.json) переопределяет
любую константу с таким же именем. Секреты лучше держать именно там, а не в коде.
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# --------------------- Telegram / Google Sheets ---------------------
TELEGRAM_BOT_TOKEN = "8322898928:AAFfmn4fQOeJKt_ShbDMbFGnPc0F3PZB8i0"
TELEGRAM_CHAT_ID = "441164219"
GOOGLE_SPEC_SHEET_URL = "https://docs.google.com/spreadsheets/d/1ugbPnYT_kFrqglr7wf_ZzvITL5hLgTIN8KjHgEYqM8k/export?format=csv"
USE_GOOGLE_SPEC = True  # Читать спец-сообщения из Google Таблицы
LICENSE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1DuOYXy7LoMsSw6QCYE0csxPy-cmULKfAZpyJI8EQRR0/edit?usp=sharing"

# --------------------- Веб-интерфейс ---------------------
WEB_HOST = "127.0.0.1"              # только локально (внутри RDP-сессии). Для доступа по сети — адрес интерфейса
WEB_PORT = 8765
OPEN_BROWSER = True                 # открыть интерфейс автоматически при старте
BROWSER_APP_MODE = True             # окно без адресной строки (chrome --app=...), если найден Bro/chrome.exe
LOGIN_DELAY_SECONDS = 40            # пауза между логинами при массовом входе
AUTO_PARSE_BATCH = 5                # сколько аккаунтов парсить одновременно

# Безопасный режим проверки: True = набирает сообщение, но НЕ отправляет его (пока не используется).
DRY_RUN_MAILING = False

# --------------------- Тюнинг поведения ---------------------
EXECUTOR_MAX_WORKERS = 128          # потоки для блокирующих вызовов Selenium (>= число аккаунтов)
COMPOSER_WAIT_SECONDS = 12          # сколько ждём появления поля ввода в чате
SEND_VERIFY_SECONDS = 6             # сколько ждём подтверждения отправки
DM_LIMIT_PAUSE_SECONDS = 4 * 3600   # пауза при явном лимите DM (тост "you've reached ...")
SEND_STALL_PAUSE_SECONDS = 30 * 60  # пауза, если подряд N отправок не подтвердились
SEND_STALL_THRESHOLD = 5
HEALTH_TIMEOUT_STRIKES = 3          # столько подряд таймаутов health-check = браузер мёртв
RECOVERY_MAX_ATTEMPTS = 5           # попыток пересоздать браузер, backoff 60s*2^n (макс 10 мин)
IDLE_HEALTH_INTERVAL = 30           # секунд между проверками неактивных (не в рассылке) браузеров
BLOCK_MEDIA_URLS = True             # резать видео/аналитику через CDP, чтобы снять нагрузку с CPU
GUI_REFRESH_MS = 3000               # период перерисовки таблицы

# --------------------- Мониторинг нагрузки (вкладка Load, logs/sysmon_*.csv) ---------------------
SYSMON_INTERVAL = 5                 # секунд между замерами CPU/RAM/процессов (0 = мониторинг выключен)
SYSMON_LOG_EVERY = 60               # раз в сколько секунд писать строку [SYSMON] в основной лог (0 = не писать)
SYSMON_ACCOUNTS_EVERY = 60          # раз в сколько секунд писать разбивку по аккаунтам в sysmon_accounts_*.csv
SYSMON_HISTORY_MINUTES = 60         # сколько истории держать в памяти для графиков вкладки Load

# --------------------- Снижение нагрузки ---------------------
IDLE_PARK_SECONDS = 180             # простаивающий браузер (не в рассылке/парсинге) через N с уводится
                                    # на about:blank: вкладка x.com без дела грузит CPU. 0 = не парковать.
TYPING_MAX_SECONDS = 90             # если "человеческий" набор идёт дольше (сервер перегружен) — остаток
                                    # текста вставляется одним куском, чтобы сообщение ушло целиком. 0 = без лимита.


def _apply_overrides() -> None:
    """Переопределяет константы значениями из config/settings.json (если файл есть)."""
    if not SETTINGS_FILE.exists():
        return
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # битый JSON не должен ронять программу
        print(f"[settings] Не удалось прочитать {SETTINGS_FILE}: {e}")
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if key.isupper() and key in globals() and not key.startswith("_"):
            globals()[key] = value


_apply_overrides()
