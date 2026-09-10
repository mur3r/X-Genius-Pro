"""
Статусы результата отправки, JS-зонды и классификация состояния страницы чата.
Ничего не знает о selenium: на вход — dict, который вернул PAGE_PROBE_JS.
"""
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Статусы результата send_message
# ---------------------------------------------------------------------------
SUCCESS = "SUCCESS"
RETRY = "RETRY"                 # временная ошибка: страница не догрузилась, X error page, таймаут
NO_INPUT = "NO_INPUT"           # чат загружен, но поля ввода нет: read-only / нас удалили из группы
NEED_RELOGIN = "NEED_RELOGIN"
LOCKED = "LOCKED"
BROWSER_CLOSED = "BROWSER_CLOSED"
LIMIT_REACHED = "LIMIT_REACHED"
FAILED = "FAILED"               # оставлен для совместимости; цикл трактует как RETRY
OK_TO_TYPE = "OK"               # внутренний вердикт classify_page: поле ввода на месте

# ---------------------------------------------------------------------------
# JS-зонд состояния страницы. Возвращает маленький dict вместо page_source (MB).
# ---------------------------------------------------------------------------
PAGE_PROBE_JS = r"""
const q = (s) => document.querySelector(s);
const composer =
    q("textarea[data-testid='dm-composer-textarea']") ||
    q("textarea[placeholder='Message']") ||
    q("textarea[aria-label='Message']") ||
    q("[data-testid='dmComposerTextInput']") ||
    q("div[role='textbox'][data-testid*='dmComposer']") ||
    q("textarea");
const send =
    q("[data-testid='dmComposerSendButton']") ||
    q("button[aria-label='Send']") ||
    q("button[aria-label='Отправить']");
const entries = document.querySelectorAll("[data-testid='messageEntry']").length;
const scroller =
    !!q("[data-testid='DmScrollerContainer']") ||
    !!q("[data-testid='DmActivityViewport']") ||
    !!q("[data-testid='DmActivityContainer']");
const toasts = Array.from(
    document.querySelectorAll("[data-testid='toast'], [role='alert'], [role='status']")
).map(e => (e.innerText || '')).join(' | ').slice(0, 600);
const body = (document.body && document.body.innerText) ? document.body.innerText : '';
let value = null;
if (composer) {
    value = ('value' in composer) ? composer.value : composer.innerText;
}
return {
    url: location.href,
    ready: document.readyState,
    hasComposer: !!composer,
    composerTag: composer ? composer.tagName.toLowerCase() : null,
    composerValue: value,
    hasSend: !!send,
    sendDisabled: send ? (!!send.disabled || send.getAttribute('aria-disabled') === 'true') : null,
    entries: entries,
    conversationLoaded: scroller || entries > 0,
    hasLoginForm: !!q("input[name='text'][autocomplete='username']"),
    hasSpinner: !!q("[role='progressbar']"),
    toasts: toasts,
    text: body.slice(0, 6000).toLowerCase()
};
"""

# Прокрутка списка чатов + сбор ссылок одним вызовом (вместо querySelectorAll('*')
# с getComputedStyle на каждом элементе и N HTTP-запросов get_attribute).
CHAT_LIST_SCROLL_JS = r"""
const anchors = Array.from(document.querySelectorAll("a[href*='/i/chat/']"));
const hrefs = anchors.map(a => a.href);
let el = anchors.length ? anchors[anchors.length - 1].parentElement : null;
let scroller = null;
while (el && el !== document.body) {
    const s = getComputedStyle(el);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 50) {
        scroller = el;
        break;
    }
    el = el.parentElement;
}
if (scroller) {
    scroller.scrollTop += Math.max(500, scroller.clientHeight * 0.8);
} else {
    window.scrollBy(0, Math.max(500, window.innerHeight * 0.8));
}
return hrefs;
"""

FOLLOWERS_PROBE_JS = r"""
const a = document.querySelector("a[href$='/verified_followers'], a[href$='/followers']");
return a ? (a.innerText || '') : null;
"""

LOGIN_PATHS = ("/i/flow/login", "/login", "/logout")
LOCK_PATHS = ("/account/access", "/account/suspended", "/login_challenge", "consent_violation_flow")

READ_ONLY_MARKERS = (
    "you can't send messages", "you can’t send messages", "can't reply to this conversation",
    "can’t reply to this conversation", "cannot send messages", "only admins can send",
    "you're no longer", "you are no longer", "you left this", "read-only", "read only",
    "this conversation doesn't exist", "this conversation doesn’t exist",
    "не можете отправлять сообщения", "вы больше не", "покинули", "только для чтения",
)
LIMIT_MARKERS = (
    "you've reached", "you’ve reached", "you have reached", "reached your limit",
    "rate limit", "too many messages", "try again later", "daily limit",
    "превышен лимит", "слишком много", "попробуйте позже",
)
PAGE_DOWN_MARKERS = (
    "this page is down", "something went wrong", "try reloading", "retry",
    "что-то пошло не так", "попробуйте снова", "перезагрузить",
)


def is_x_url(url: Optional[str]) -> bool:
    """True, если браузер реально находится на x.com / twitter.com (а не на
    chrome-error://, about:blank, странице ошибки прокси и т.п.)."""
    if not url:
        return False
    u = url.lower()
    return u.startswith("https://x.com") or u.startswith("https://www.x.com") \
        or u.startswith("https://twitter.com") or u.startswith("https://www.twitter.com") \
        or u.startswith("https://mobile.x.com") or u.startswith("https://mobile.twitter.com")


def chat_id_from_url(group_url: str) -> str:
    return group_url.rstrip("/").split("/")[-1].split("?")[0]


def classify_page(probe: Optional[dict], chat_id: str = "") -> Tuple[str, str]:
    """
    Классифицирует состояние страницы чата ДО набора текста.

    Возвращает (вердикт, причина). Вердикты:
      OK_TO_TYPE   — поле ввода на месте, можно печатать;
      NO_INPUT     — чат загружен (виден список сообщений), но поля ввода нет:
                     с высокой вероятностью группа read-only / нас удалили;
      NEED_RELOGIN — редирект на логин;
      LOCKED       — чекпоинт / бан;
      RETRY        — временная проблема (не догрузилось, X error page, редирект в никуда).
    """
    if not probe or not isinstance(probe, dict):
        return RETRY, "probe failed"

    url = (probe.get("url") or "").lower()
    text = probe.get("text") or ""

    if any(p in url for p in LOGIN_PATHS) or probe.get("hasLoginForm"):
        return NEED_RELOGIN, "login page"
    if any(p in url for p in LOCK_PATHS):
        return LOCKED, "lock/checkpoint page"

    if probe.get("hasComposer"):
        return OK_TO_TYPE, ""

    # Поля ввода нет. Разбираемся, почему.
    if probe.get("conversationLoaded"):
        for m in READ_ONLY_MARKERS:
            if m in text:
                return NO_INPUT, f"marker: {m}"
        return NO_INPUT, "conversation loaded, composer missing"

    if chat_id and chat_id not in url and is_x_url(url):
        # X увёл нас с чата (обычно на /messages) — чат недоступен этому аккаунту.
        for m in READ_ONLY_MARKERS:
            if m in text:
                return NO_INPUT, f"redirected, marker: {m}"
        return NO_INPUT, f"redirected to {url[:80]}"

    if not is_x_url(url):
        return RETRY, f"not on x.com: {url[:80]}"
    if any(m in text for m in PAGE_DOWN_MARKERS):
        return RETRY, "X error page"
    if probe.get("hasSpinner") or probe.get("ready") != "complete":
        return RETRY, "page still loading"
    return RETRY, "composer not found"


def toasts_indicate_limit(probe: Optional[dict]) -> bool:
    if not probe:
        return False
    t = (probe.get("toasts") or "").lower()
    return any(m in t for m in LIMIT_MARKERS)


def normalize_for_compare(s: Optional[str]) -> str:
    """Сравнение текста в поле с тем, что мы хотели набрать, с допуском на пробелы."""
    if not s:
        return ""
    return " ".join(s.replace("\r\n", "\n").split())


# ---------------------------------------------------------------------------
# Классификация ошибок драйвера
# ---------------------------------------------------------------------------
_TIMEOUT_MARKERS = ("read timed out", "timed out", "timeout")
_CLOSED_MARKERS = (
    "chrome not reachable", "invalid session id", "session deleted", "no such window",
    "target window already closed", "not connected to devtools", "disconnected",
    "target page, context or browser has been closed", "websocketwithurl",
    "connection refused", "winerror 10061", "failed to establish a new connection",
    "browser has been closed", "web view not found", "no such execution context",
    "session not created", "actively refused",
)
_CLOSED_TYPES = ("InvalidSessionIdException", "NoSuchWindowException")


def classify_driver_error(exc: BaseException) -> str:
    """
    'closed'  — браузер/драйвер мёртв, нужно пересоздавать;
    'timeout' — команда не успела (перегруз сервера / долгая загрузка), браузер жив;
    'other'   — всё остальное (элемент не найден и т.п.).
    """
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in _CLOSED_TYPES:
        return "closed"
    if name == "TimeoutException" or any(m in msg for m in _TIMEOUT_MARKERS):
        # "timed out receiving message from renderer" — тоже временное
        if not any(m in msg for m in ("connection refused", "winerror 10061", "chrome not reachable")):
            return "timeout"
    if any(m in msg for m in _CLOSED_MARKERS):
        return "closed"
    return "other"
