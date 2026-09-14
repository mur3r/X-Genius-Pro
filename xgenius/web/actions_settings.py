"""
Операции веб-интерфейса, часть 2 (миксин Actions): настройки рассылки и комментариев,
экспорт чатов, сброс ошибок, окно браузера, статистика.
"""
import csv
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

from xgenius.models import AccountState, CommentSettings, CycleSettings


class ActionError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""


def _parse_date(value: str, end: bool = False) -> datetime:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            d = datetime.strptime(value.strip(), fmt)
            return d.replace(hour=23, minute=59, second=59) if end else d
        except ValueError:
            continue
    raise ActionError(f"Неверный формат даты: {value}")


class SettingsActions:
    """Методы Actions; self.e (Engine), self.am, self._state, self._log определены в actions.py."""

    # ------------------------------------------------------------------ settings
    @staticmethod
    def _cycle_from(data: dict) -> CycleSettings:
        try:
            return CycleSettings(
                messages_per_cycle=int(data.get("messages_per_cycle", 16)),
                rest_time_minutes=int(data.get("rest_time_minutes", 30)),
                retweet_count=int(data.get("retweet_count", 0)),
                max_total_retweets=int(data.get("max_total_retweets", 0)),
                media_enabled=bool(data.get("media_enabled", False)),
            )
        except (TypeError, ValueError):
            raise ActionError("Invalid settings values!")

    @staticmethod
    def _messages_from(items) -> List[Dict[str, Any]]:
        out = []
        for m in items or []:
            text = (m.get("text") or "").strip()
            if not text:
                continue
            try:
                count = int(m.get("count", 1))
            except (TypeError, ValueError):
                count = 1
            out.append({"text": text, "count": count if count > 0 else 1})
        return out

    def get_settings(self, username: str) -> dict:
        st = self._state(username)
        cycle = self.e.cycle_manager.get_cycle_settings(username)
        groups = len(st.groups) if st and st.groups else len(self.am.load_saved_groups(username))
        return {
            "cycle": cycle.__dict__,
            "messages": self.e.message_manager.get_messages(username),
            "groups_count": groups,
            "chat_cache": len(self.e.task_scheduler.chat_store.all_groups(username)),
            "disabled": self.e.task_scheduler.chat_store.disabled_groups(username),
        }

    def save_settings(self, username: str, cycle: dict, messages: list) -> None:
        self._save_settings_for_user(username, self._cycle_from(cycle), self._messages_from(messages))

    def _save_settings_for_user(self, username: str, cycle: CycleSettings, messages: List[Dict[str, Any]]) -> None:
        self.e.cycle_manager.save_cycle_settings(username, cycle)
        self.e.message_manager.save_messages(username, messages)
        st = self._state(username)
        if st:
            st.cycle_settings = cycle
            st.mailing_messages = messages
            st.media_enabled = cycle.media_enabled
            st.message_index = 0
            st.message_sent_count = 0
        self._log(f"Settings updated: Cycle={cycle}, Messages Count={len(messages)}", username)
        self.e.notify()

    def mass_settings(self, usernames: List[str], mode: str, update_settings: bool, update_messages: bool,
                      cycle: dict, messages: list) -> int:
        if not update_settings and not update_messages:
            raise ActionError("Nothing selected to update!")
        new_msgs = self._messages_from(messages)
        cycle_obj = self._cycle_from(cycle) if update_settings else None
        if mode == "append" and (not update_messages or not new_msgs):
            raise ActionError("Append needs 'Update Messages' and at least one message text.")
        for u in usernames:
            final_cycle = cycle_obj if update_settings else self.e.cycle_manager.get_cycle_settings(u)
            if not update_messages:
                final_msgs = self.e.message_manager.get_messages(u)
            elif mode == "append":
                final_msgs = self.e.message_manager.get_messages(u)
                for m in new_msgs:
                    if m not in final_msgs:
                        final_msgs.append(m)
            else:
                final_msgs = new_msgs
            self._save_settings_for_user(u, final_cycle, final_msgs)
        return len(usernames)

    def get_comment_settings(self, username: str) -> dict:
        return self.e.comment_manager.get_comment_settings(username).__dict__

    def save_comment_settings(self, username: str, data: dict) -> None:
        try:
            limit = int(data.get("daily_limit") or 0)
        except (TypeError, ValueError):
            raise ActionError("Daily limit must be a number")
        s = CommentSettings(
            enabled=bool(data.get("enabled")),
            targets_file=(data.get("targets_file") or "").strip(),
            comments_file=(data.get("comments_file") or "").strip(),
            photo_path=(data.get("photo_path") or "").strip(),
            daily_limit=limit,
        )
        self.e.comment_manager.save_comment_settings(username, s)
        st = self._state(username)
        if st:
            st.comment_settings = s
        self.e.notify()

    # ------------------------------------------------------------------ misc
    def export_chats(self, usernames: List[str]) -> Tuple[str, str]:
        path = self.am.export_groups_to_file(usernames)
        with open(path, "r", encoding="utf-8") as f:
            return path, f.read()

    def clear_groups(self, username: str) -> None:
        st = self._state(username)
        if st:
            st.groups.clear()
            self.am.save_groups()
        self.e.task_scheduler.chat_store.replace_groups(username, [])
        self._log("Groups cleared", username)
        self.e.notify()

    def reset_errors(self) -> int:
        n = 0
        for u, st in self.am.accounts.items():
            if st.status_reason in ERROR_STATUSES_RESET:
                st.status_reason = ""
                self._log("Статус сброшен вручную через Refresh", u)
                n += 1
        self.e.notify()
        return n

    async def view(self, username: str) -> None:
        st = self._state(username)
        if not st or not st.browser:
            raise ActionError(f"Browser for {username} is not open!")
        browser = st.browser
        parked = st.parked

        def _front():
            if parked:
                # Припаркованный браузер стоит на about:blank — оператору нужен x.com
                try:
                    browser.get("https://x.com/home")
                except Exception:
                    pass
            try:
                rect = browser.get_window_rect()
                if rect["x"] < -1000 or rect["y"] < -1000:
                    rect = {"x": 50, "y": 50, "width": 1050, "height": 800}
            except Exception:
                rect = {"x": 50, "y": 50, "width": 1050, "height": 800}
            browser.minimize_window()
            import time
            time.sleep(0.2)
            browser.set_window_rect(x=rect["x"], y=rect["y"], width=rect["width"], height=rect["height"])
            browser.switch_to.window(browser.current_window_handle)

        await self.e.loop.run_in_executor(None, _front)
        st.parked = False

    # ------------------------------------------------------------------ stats
    def daily_stats(self, username: str) -> dict:
        st = self._state(username)
        return {"messages_24h": self.e.stats_manager.get_stats_for_24h(username),
                "comments_today": st.comments_sent_24h if st else 0,
                "messages_total": st.messages_sent if st else 0}

    def history(self, date_from: str, date_to: str) -> dict:
        start, end = _parse_date(date_from), _parse_date(date_to, end=True)
        data = self.e.stats_manager.get_detailed_stats(start, end)
        data.sort(key=lambda x: x["msg_period"], reverse=True)
        totals = {k: sum(r[k] for r in data) for k in
                  ("msg_period", "rt_period", "comm_period", "msg_total", "rt_total", "comm_total")}
        return {"rows": data, "totals": totals}

    def history_csv(self, date_from: str, date_to: str) -> str:
        rows = self.history(date_from, date_to)["rows"]
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=["Username", "MSG (Period)", "RT (Period)", "Comm (Period)",
                                                 "MSG (Total)", "RT (Total)", "Comm (Total)"], delimiter=";")
        writer.writeheader()
        for r in rows:
            writer.writerow({"Username": r["username"], "MSG (Period)": r["msg_period"], "RT (Period)": r["rt_period"],
                             "Comm (Period)": r["comm_period"], "MSG (Total)": r["msg_total"],
                             "RT (Total)": r["rt_total"], "Comm (Total)": r["comm_total"]})
        return buf.getvalue()

    def delete_stats(self, username: str) -> None:
        self.e.stats_manager.delete_stats_for_user(username)

    @staticmethod
    def quick_range(days: int, single_day: bool) -> Tuple[str, str]:
        now = datetime.now()
        if single_day:
            d = (now - timedelta(days=days)).strftime("%Y-%m-%d")
            return d, d
        return (now - timedelta(days=days)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    @staticmethod
    def random_wait() -> float:  # used by tests/tools
        return random.uniform(15, 30)
