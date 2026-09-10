"""
Пути проекта: базовая папка (Bro/chrome.exe, Drivers/chromedriver.exe, данные аккаунтов),
файлы состояния. Базовая папка хранится в paths.json рядом с main.py; выбирается
на экране Setup веб-интерфейса (раньше — диалог tkinter при первом запуске).
"""
import json
from pathlib import Path
from typing import Optional, Tuple


class ConfigError(Exception):
    pass


def paths_file() -> Path:
    return Path.cwd() / "paths.json"


def read_saved_base_dir() -> Optional[Path]:
    f = paths_file()
    if not f.exists():
        return None
    try:
        with open(f, "r", encoding="utf-8") as fh:
            base = json.load(fh).get("base_dir", "")
        return Path(base) if base else None
    except Exception:
        return None


def save_base_dir(base_dir: Path) -> None:
    with open(paths_file(), "w", encoding="utf-8") as fh:
        json.dump({"base_dir": str(base_dir)}, fh, indent=4)


def get_paths_from_base(base_folder: Path) -> Tuple[Path, Path]:
    chrome_path = base_folder / "Bro" / "chrome.exe"
    chromedriver_path = base_folder / "Drivers" / "chromedriver.exe"
    return chrome_path, chromedriver_path


class Config:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = read_saved_base_dir()
        if base_dir is None:
            raise ConfigError("Базовая папка не выбрана (нет paths.json). Откройте экран Setup.")
        self.base_dir = Path(base_dir)
        self.chrome_path, self.chromedriver_path = get_paths_from_base(self.base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profiles_dir = self.base_dir / "browser_profiles"
        self.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_file = self.base_dir / "accounts.json"
        self.last_sent_file = self.base_dir / "last_sent.json"
        self.message_file = self.base_dir / "message.txt"
        self.account_messages_file = self.base_dir / "account_messages.json"
        self.account_groups_file = self.base_dir / "account_groups.json"
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.cycle_settings_file = self.base_dir / "cycle_settings.json"
        self.comment_settings_file = self.base_dir / "comment_settings.json"
        self.sending_stats_file = self.base_dir / "sending_stats.json"
        self.retweet_stats_file = self.base_dir / "retweet_stats.json"
        self.comm_stats_file = self.base_dir / "comment_stats.json"

    def get_profile_dir(self, username: str) -> Path:
        profile_dir = self.browser_profiles_dir / f"profile_{username}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir
