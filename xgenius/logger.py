"""
Логгер с файловым хендлером и кольцевым буфером для окна Monitor.
"""

import logging
from collections import deque
from datetime import datetime
from typing import Callable, List, Optional

from xgenius.config import Config


class Logger:
    def __init__(self, config: Config, global_observer_level: int = logging.INFO):
        self.config = config
        self.global_observer_level = global_observer_level
        # deque с maxlen вместо list.pop(0) (O(n) на каждой записи) + счётчик seq,
        # чтобы окно Monitor дорисовывало только новые строки.
        self.log_buffer = deque(maxlen=1000)
        self.seq = 0
        log_file = config.logs_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
        self.logger = logging.getLogger("TwitterBot")
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.INFO)
        self.observers: List[Callable[[str], None]] = []

    def add_observer(self, callback: Callable[[str], None]) -> None:
        if callback not in self.observers:
            self.observers.append(callback)

    def log(self, message: str, level: int = logging.INFO, account: Optional[str] = None) -> None:
        if "GetHandleVerifier" in message:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = f"@{account}" if account else ""
        formatted = f"[{ts}] {prefix} - {message}"
        self.log_buffer.append(formatted)
        self.seq += 1

        self.logger.log(level, formatted)
        for obs in self.observers:
            obs(formatted)

    def info(self, message: str, account: Optional[str] = None) -> None:
        self.log(message, level=logging.INFO, account=account)

    def warning(self, message: str, account: Optional[str] = None) -> None:
        self.log(message, level=logging.WARNING, account=account)

    def error(self, message: str, account: Optional[str] = None) -> None:
        self.log(message, level=logging.ERROR, account=account)

    def clear_logs(self):
        try:
            for lf in self.config.logs_dir.glob("*.log"):
                lf.unlink()
            self.log_buffer.clear()
            self.info("Logs cleared")
        except Exception as e:
            self.error(f"Failed to clear logs: {e}")
