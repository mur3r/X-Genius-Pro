"""
Чистая логика без selenium/tkinter (покрыта юнит-тестами в tests/):
  page_state   — статусы отправки, JS-зонды, классификация состояния страницы и ошибок драйвера;
  chat_store   — хранилище групп аккаунта (кеш / очередь / страйки / отключённые);
  typing_split — разбиение текста для "человеческого" набора (BMP vs emoji);
  procinfo     — принадлежность процессов Chrome аккаунтам, строка-пульс мониторинга.
"""
from .page_state import (  # noqa: F401
    SUCCESS, RETRY, NO_INPUT, NEED_RELOGIN, LOCKED, BROWSER_CLOSED, LIMIT_REACHED, FAILED, OK_TO_TYPE,
    PAGE_PROBE_JS, CHAT_LIST_SCROLL_JS, FOLLOWERS_PROBE_JS,
    LOGIN_PATHS, LOCK_PATHS, READ_ONLY_MARKERS, LIMIT_MARKERS, PAGE_DOWN_MARKERS,
    is_x_url, chat_id_from_url, classify_page, toasts_indicate_limit, normalize_for_compare,
    classify_driver_error,
)
from .chat_store import (  # noqa: F401
    ChatStore, NO_INPUT_STRIKES_TO_DISABLE, RETRY_STRIKES_TO_DISABLE, DISABLED_TTL_HOURS,
)
from .typing_split import is_bmp, split_for_typing  # noqa: F401
from .procinfo import (  # noqa: F401
    account_from_cmdline, chrome_role, classify_chrome_process, fmt_ms, heartbeat_line,
)
