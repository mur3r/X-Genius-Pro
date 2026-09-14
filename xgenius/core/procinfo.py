"""
Чистые помощники для мониторинга нагрузки (без psutil): к какому аккаунту относится
процесс Chrome по его командной строке, роль процесса, форматирование строки-пульса.
"""
import re
from typing import Any, Dict, Optional

# --user-data-dir=<...>\browser_profiles\profile_<username>  (кавычки/слеши любые)
_PROFILE_RE = re.compile(r"browser_profiles[\\/]+profile_([^\\/\"'\s]+)", re.IGNORECASE)
_TYPE_RE = re.compile(r"--type=([a-z-]+)", re.IGNORECASE)


def account_from_cmdline(cmdline: str) -> Optional[str]:
    """Имя аккаунта из --user-data-dir=...\\browser_profiles\\profile_<username>, иначе None."""
    if not cmdline:
        return None
    m = _PROFILE_RE.search(cmdline)
    return m.group(1) if m else None


def chrome_role(name: str, cmdline: str) -> str:
    """'driver' (chromedriver.exe) | 'browser' (главный процесс) | 'renderer' | 'gpu' | 'utility' | ..."""
    n = (name or "").lower()
    if "chromedriver" in n:
        return "driver"
    m = _TYPE_RE.search(cmdline or "")
    if not m:
        return "browser"
    t = m.group(1).lower()
    if t.startswith("renderer"):
        return "renderer"
    if t.startswith("gpu"):
        return "gpu"
    if t.startswith("utility"):
        return "utility"
    return t


def classify_chrome_process(name: str, cmdline: str, profiles_marker: str, webui_marker: str = "") -> Dict[str, Any]:
    """
    Кому принадлежит процесс Chrome:
      ours=True, account=<username>  — браузер аккаунта (наш --user-data-dir);
      ours=True, account='_webui'    — окно интерфейса X-Genius (chrome --app);
      ours=False                     — чужой Chrome на сервере (не трогаем, но считаем).
    """
    cmd = (cmdline or "").lower()
    role = chrome_role(name, cmd)
    if profiles_marker and profiles_marker.lower() in cmd:
        return {"ours": True, "account": account_from_cmdline(cmd) or "_other", "role": role}
    if webui_marker and webui_marker.lower() in cmd:
        return {"ours": True, "account": "_webui", "role": role}
    return {"ours": False, "account": None, "role": role}


def fmt_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "—"
    if ms >= 1000:
        return f"{ms / 1000:.1f} с"
    return f"{int(round(ms))} мс"


def heartbeat_line(s: Dict[str, Any]) -> str:
    """Строка [SYSMON] для основного лога — по ней в bot_*.log видно нагрузку в момент любой ошибки."""
    cpu = s.get("cpu", {})
    mem = s.get("mem", {})
    ch = s.get("chrome", {})
    py = s.get("python", {})
    ex = s.get("executor", {})
    en = s.get("engine", {})
    parts = [
        f"CPU {cpu.get('total', 0):.0f}% (ядер >90%: {cpu.get('busy_cores', 0)}/{cpu.get('count', 0)})",
        f"RAM {mem.get('used_gb', 0):.0f}/{mem.get('total_gb', 0):.0f} GB",
        f"Chrome {ch.get('procs', 0)} проц/{ch.get('threads', 0)} потоков = {ch.get('cpu', 0):.0f}% CPU, {ch.get('rss_gb', 0):.1f} GB",
        f"Python {py.get('cpu', 0):.0f}%, потоков {py.get('threads', 0)}",
        f"Selenium: в работе {ex.get('inflight', 0)}/{ex.get('max', 0)}, вызовов {ex.get('calls', 0)}, "
        f"ср. {fmt_ms(ex.get('avg_ms'))}, макс {fmt_ms(ex.get('max_ms'))}",
        f"loop lag {fmt_ms(s.get('loop_lag_ms'))}",
        f"браузеров {en.get('browsers', 0)} (mailing {en.get('mailing', 0)}, parsing {en.get('parsing', 0)})",
    ]
    if ch.get("other_procs"):
        parts.append(f"чужой Chrome: {ch['other_procs']} проц, {ch.get('other_cpu', 0):.0f}% CPU")
    return "[SYSMON] " + " · ".join(parts)
