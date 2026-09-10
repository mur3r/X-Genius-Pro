"""
Управление процессами chromedriver / chrome: принудительное закрытие, зачистка сирот.
"""

import subprocess
import sys
import threading

import psutil


# --------------------- Функция жесткой очистки процессов ---------------------
def force_kill_chromedrivers():
    """Принудительно убивает все процессы chromedriver.exe"""
    try:
        if sys.platform == 'win32':
            subprocess.call("taskkill /F /IM chromedriver.exe /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error cleaning up drivers: {e}")


def kill_orphan_chrome(profiles_dir) -> int:
    """
    Убивает процессы chrome, которые запущены с нашим --user-data-dir (папка browser_profiles),
    но уже никем не управляются. Раньше при закрытии программы убивался только chromedriver.exe,
    а chrome.exe оставался висеть: держал профиль (следующий Login падал с
    'user data directory is already in use') и грузил CPU/RAM.
    Чужой Chrome (без нашего профиля в командной строке) не трогаем.
    """
    killed = 0
    marker = str(profiles_dir).lower()
    if not marker:
        return 0
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "chrome" not in name:
                    continue
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                if marker in cmd:
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        print(f"kill_orphan_chrome error: {e}")
    return killed


def hard_close_browser(browser, timeout: float = 15.0) -> None:
    """
    Закрывает браузер гарантированно: quit() с таймаутом (у зависшего chromedriver quit()
    может блокироваться до 2 минут), затем добиваем дерево процессов chromedriver -> chrome.
    """
    if browser is None:
        return
    pid = getattr(browser, "_xg_pid", None)
    if pid is None:
        try:
            pid = browser.service.process.pid
        except Exception:
            pid = None

    def _quit():
        try:
            browser.quit()
        except Exception:
            pass

    t = threading.Thread(target=_quit, daemon=True)
    t.start()
    t.join(timeout)

    if pid and psutil.pid_exists(pid):
        try:
            root = psutil.Process(pid)
            children = root.children(recursive=True)
            for c in children:
                try:
                    c.kill()
                except Exception:
                    pass
            try:
                root.kill()
            except Exception:
                pass
        except Exception:
            pass
