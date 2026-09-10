"""
Engine: собирает менеджеры движка, отдаёт снимок состояния для веб-интерфейса,
хранит лицензию. Раньше эту роль выполнял класс GUI (tkinter): AccountManager и
TaskScheduler по-прежнему получают ссылку на "gui_instance" — теперь это Engine
с теми же атрибутами (telegram_bot_instance, update_account_table_threadsafe).
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xgenius import __version__
from xgenius.accounts.manager import AccountManager
from xgenius.config import Config
from xgenius.logger import Logger
from xgenius.managers import CommentManager, CycleManager, MessageManager
from xgenius.process_utils import kill_orphan_chrome
from xgenius.scheduler import TaskScheduler
from xgenius.settings import EXECUTOR_MAX_WORKERS
from xgenius.stats import StatsManager
from xgenius.twitter.operations import TwitterOperations

# Статусы, которые считаем "ошибкой" в сводке (всё, кроме служебных пауз/восстановления)
_NON_ERROR_STATUS_PREFIXES = ("RECOVERING", "DM LIMIT", "SEND STALL")


class Engine:
    def __init__(self, loop: asyncio.AbstractEventLoop, base_dir: Optional[Path] = None):
        self.loop = loop
        self.telegram_bot_instance = None  # TelegramBotManager отсутствует в сборке
        self.started_at = datetime.now()

        self.config = Config(base_dir)
        self.logger = Logger(self.config)
        self.stats_manager = StatsManager(self.config)
        self.account_manager = AccountManager(self.config, self.logger)
        self.message_manager = MessageManager(self.config, self.logger)
        self.cycle_manager = CycleManager(self.config, self.logger)
        self.comment_manager = CommentManager(self.config, self.logger)
        self.twitter_ops = TwitterOperations(self.logger, self.stats_manager)
        self.task_scheduler = TaskScheduler(self.logger, self.notify, self.account_manager)
        self.account_manager.set_gui_instance(self)

        # Пул потоков для блокирующих вызовов Selenium (>= число аккаунтов)
        self.loop.set_default_executor(ThreadPoolExecutor(max_workers=EXECUTOR_MAX_WORKERS, thread_name_prefix="xg"))
        try:
            killed = kill_orphan_chrome(self.config.browser_profiles_dir)
            if killed:
                self.logger.info(f"Добиты осиротевшие процессы chrome с прошлого запуска: {killed}")
        except Exception:
            pass

        self._changed = asyncio.Event()
        self._tasks: List[asyncio.Task] = [
            self.loop.create_task(self.account_manager.idle_health_watchdog()),
        ]
        self.logger.warning("Telegram bot: модуль TelegramBotManager отсутствует в сборке — бот не запущен.")
        self.logger.info(f"X-Genius {__version__}: движок запущен, база: {self.config.base_dir}")

    # ------------------------------------------------------------------
    # Совместимость с AccountManager / TaskScheduler (раньше это был GUI)
    # ------------------------------------------------------------------
    def notify(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self._changed.set)
        except RuntimeError:
            pass

    def update_account_table_threadsafe(self) -> None:
        self.notify()

    def update_account_table(self, force: bool = False) -> None:
        self.notify()

    async def wait_change(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
            self._changed.clear()
            return True
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------------
    # Снимок состояния для интерфейса
    # ------------------------------------------------------------------
    def _status_is_error(self, reason: str) -> bool:
        if not reason:
            return False
        return not reason.upper().startswith(_NON_ERROR_STATUS_PREFIXES)

    def account_rows(self) -> List[Dict[str, Any]]:
        am = self.account_manager
        rows = []
        running = set(self.task_scheduler.running_tasks.keys())
        for r in am.get_table_data():
            acc = r["account"]
            u = r["username"]
            st = am.accounts.get(u)
            msgs = self.message_manager.account_messages.get(u)
            rows.append({
                "index": r["index"] + 1,
                "username": u,
                "group": acc.get("group", "") or "",
                "proxy": acc.get("proxy", "") or "",
                "has_token": bool(acc.get("auth_token")),
                "has_password": bool(acc.get("password")),
                "status": r["status_text"],
                "status_color": r["status_color"],
                "status_reason": st.status_reason if st else "",
                "groups_count": r["groups_count"],
                "last_launch": r["last_launch"],
                "is_active": bool(st and st.is_active),
                "is_mailing": bool(st and st.is_mailing),
                "is_paused": bool(st and st.is_paused),
                "is_parsing": bool(st and st.is_parsing),
                "need_relogin": bool(st and st.need_relogin),
                "has_browser": bool(st and st.browser),
                "running": u in running,
                "messages_sent": st.messages_sent if st else 0,
                "msg_24h": self.stats_manager.get_stats_for_24h(u),
                "retweets": st.retweets_count if st else 0,
                "comments_24h": st.comments_sent_24h if st else 0,
                "followers": st.followers_count if st else 0,
                "has_messages": bool(msgs),
                "queue_len": self.task_scheduler.chat_store.queue_len(u),
                "disabled_groups": len(self.task_scheduler.chat_store.disabled_groups(u)),
            })
        return rows

    def summary(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = {"all": len(rows), "paused": 0, "error": 0, "ready": 0, "mailing": 0, "inactive": 0,
                 "messages": 0, "retweets": 0, "comments": 0, "groups": 0, "browsers": 0}
        for r in rows:
            total["messages"] += r["messages_sent"]
            total["retweets"] += r["retweets"]
            total["comments"] += r["comments_24h"]
            total["groups"] += r["groups_count"]
            if r["has_browser"]:
                total["browsers"] += 1
            if r["is_paused"]:
                total["paused"] += 1
            elif self._status_is_error(r["status_reason"]):
                total["error"] += 1
            elif r["is_mailing"]:
                total["mailing"] += 1
            elif r["is_active"]:
                total["ready"] += 1
            else:
                total["inactive"] += 1
        return total

    def snapshot(self) -> Dict[str, Any]:
        rows = self.account_rows()
        groups = sorted({r["group"] for r in rows if r["group"]})
        return {
            "phase": "ready",
            "version": __version__,
            "base_dir": str(self.config.base_dir),
            "summary": self.summary(rows),
            "groups": groups,
            "accounts": rows,
            "log_seq": self.logger.seq,
        }

    def logs_since(self, seq: int) -> Tuple[int, List[str]]:
        current = self.logger.seq
        new_count = current - seq
        if new_count <= 0:
            return current, []
        buffer = list(self.logger.log_buffer)
        if new_count >= len(buffer):
            return current, buffer
        return current, buffer[-new_count:]

    # ------------------------------------------------------------------
    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        for username in list(self.task_scheduler.running_tasks.keys()):
            try:
                self.task_scheduler.stop_account_cycle(username)
            except Exception:
                pass
        try:
            self.account_manager.stop_worker = True
        except Exception:
            pass
        try:
            await self.loop.run_in_executor(None, self.account_manager.shutdown_all_browsers)
        except Exception as e:
            self.logger.error(f"Ошибка при закрытии браузеров: {e}")
