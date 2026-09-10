"""
Операции над аккаунтами для веб-интерфейса. Это перенесённая логика прежних
GUI-миксинов (sessions / login_parse / dialogs / settings_windows), без tkinter:
никаких потоков и messagebox — всё выполняется в asyncio-цикле движка.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from xgenius.models import AccountCredentials, AccountState
from xgenius.process_utils import hard_close_browser, kill_orphan_chrome
from xgenius.settings import AUTO_PARSE_BATCH, LOGIN_DELAY_SECONDS
from xgenius.web.actions_settings import ActionError, SettingsActions  # noqa: F401

ERROR_STATUSES_RESET = ("Error", "LOCKED", "EMAIL LOCK", "LOCKED (CAPTCHA)", "RELOGIN FAILED", "BROWSER_CLOSED")


def _credentials(acc: dict) -> AccountCredentials:
    return AccountCredentials(
        username=acc["username"],
        password=acc.get("password", ""),
        proxy=acc.get("proxy"),
        user_agent=acc.get("user_agent"),
        headless=acc.get("headless", False),
        group=acc.get("group", ""),
        auth_token=acc.get("auth_token"),
        ct0_token=acc.get("ct0_token"),
    )


class Actions(SettingsActions):
    def __init__(self, engine):
        self.e = engine
        self._busy: set = set()  # аккаунты, для которых уже идёт логин/парсинг

    # ------------------------------------------------------------------ helpers
    @property
    def am(self):
        return self.e.account_manager

    def _account(self, username: str) -> Optional[dict]:
        return next((a for a in self.am.load_accounts() if a.get("username") == username), None)

    def _state(self, username: str) -> Optional[AccountState]:
        return self.am.accounts.get(username)

    def _log(self, msg: str, username: Optional[str] = None, level: str = "info") -> None:
        getattr(self.e.logger, level)(msg, username)

    def _apply_account_settings(self, state: AccountState) -> None:
        u = state.username
        state.mailing_messages = self.e.message_manager.get_messages(u)
        state.cycle_settings = self.e.cycle_manager.get_cycle_settings(u)
        state.comment_settings = self.e.comment_manager.get_comment_settings(u)
        state.media_enabled = state.cycle_settings.media_enabled

    # ------------------------------------------------------------------ login
    async def login_one(self, username: str) -> bool:
        acc = self._account(username)
        if not acc:
            self._log("Аккаунт не найден в accounts.json", username, "error")
            return False
        st = self._state(username)
        if st and st.is_active:
            self._log("Аккаунт уже активен", username)
            return True
        if username in self._busy:
            self._log("Логин уже выполняется", username, "warning")
            return False
        self._busy.add(username)
        try:
            self._log("Beginning login process", username)
            await asyncio.wait_for(self.am.login_account(_credentials(acc)), timeout=240)
            st = self._state(username)
            if st:
                self._apply_account_settings(st)
            self._log("Login successful!", username)
            return True
        except asyncio.TimeoutError:
            self._log("Login timeout (240s)", username, "error")
            return False
        except Exception as ex:
            self._log(f"Login failed: {ex}", username, "error")
            return False
        finally:
            self._busy.discard(username)
            self.e.notify()

    async def login_many(self, usernames: List[str], delay: int = LOGIN_DELAY_SECONDS) -> None:
        total = len(usernames)
        ok, failed = 0, []
        for i, u in enumerate(usernames):
            self._log(f"Starting login ({i + 1}/{total})", u)
            if await self.login_one(u):
                ok += 1
            else:
                failed.append(u)
            if i < total - 1:
                await asyncio.sleep(delay)
        if failed:
            self._log(f"Login completed: {ok} success, {len(failed)} errors. Failed: {', '.join(failed)}")
        else:
            self._log(f"Login completed: {ok}/{total} accounts successfully logged in")

    def start_login(self, usernames: List[str]) -> int:
        usernames = [u for u in usernames if u not in self._busy]
        if not usernames:
            raise ActionError("Нечего запускать: аккаунты не выбраны или уже логинятся")
        if len(usernames) == 1:
            self.e.loop.create_task(self.login_one(usernames[0]))
        else:
            self.e.loop.create_task(self.login_many(usernames))
        return len(usernames)

    # ------------------------------------------------------------------ parse
    async def parse_one(self, username: str) -> bool:
        st = self._state(username)
        if not st or not st.browser:
            self._log("Cannot parse groups: Account not logged in", username, "error")
            return False
        if username in self._busy:
            return False
        self._busy.add(username)
        st.is_parsing = True
        self.e.notify()
        try:
            self._log("Starting to parse groups...", username)
            groups = await self.e.twitter_ops.find_groups(st.browser, username)
            if not groups:
                self._log("No groups found during parsing", username, "warning")
                return False
            all_groups, added = self.e.task_scheduler.chat_store.merge_parsed(username, groups)
            self._log(f"Парсинг: найдено {len(groups)}, новых {added}, всего в кеше {len(all_groups)}", username)
            st.groups = set(all_groups)
            self.am.save_groups()
            try:
                with open(self.e.config.base_dir / f"groups_{username}.json", "w", encoding="utf-8") as f:
                    json.dump(sorted(all_groups), f, ensure_ascii=False, indent=4)
            except Exception:
                pass
            return True
        except Exception as ex:
            self._log(f"Error parsing groups: {ex}", username, "error")
            return False
        finally:
            st.is_parsing = False
            self._busy.discard(username)
            self.e.notify()

    async def parse_many(self, usernames: List[str], batch_size: int = AUTO_PARSE_BATCH) -> None:
        self._log(f"--- STARTED AUTO PARSE: {len(usernames)} accounts ---")
        for i in range(0, len(usernames), batch_size):
            batch = usernames[i:i + batch_size]
            self._log(f"Processing batch {i // batch_size + 1}: {batch}")
            await asyncio.gather(*(self.parse_one(u) for u in batch), return_exceptions=True)
            await asyncio.sleep(3)
        self._log("--- AUTO PARSE COMPLETED ---")

    def start_parse(self, usernames: List[str]) -> int:
        active = [u for u in usernames if self._state(u) and self._state(u).is_active and u not in self._busy]
        if not active:
            raise ActionError("Нет активных (залогиненных) аккаунтов среди выбранных")
        self.e.loop.create_task(self.parse_many(active))
        return len(active)

    # ------------------------------------------------------------------ mailing
    def start_mailing(self, username: str) -> Tuple[bool, str]:
        st = self._state(username)
        if not st or not st.browser:
            return False, "Account must be logged in first!"
        if not st.groups:
            st.groups = self.am.load_saved_groups(username)
        if not st.mailing_messages:
            st.mailing_messages = self.e.message_manager.get_messages(username)
        if not st.mailing_messages:
            return False, "No messages found! Please set messages in settings."
        if username in self.e.task_scheduler.running_tasks:
            return False, "Mailing is already running for this account."
        st.is_mailing = True
        st.is_paused = False
        self._log("Starting mailing process... Группы будут собраны автоматически из iChat.", username)
        self.e.task_scheduler.start_account_cycle(st, self.e.twitter_ops, self.am, humanize=True)
        self.e.notify()
        return True, ""

    def start_mailing_many(self, usernames: List[str]) -> Tuple[int, List[str]]:
        started, errors = 0, []
        for u in usernames:
            ok, msg = self.start_mailing(u)
            if ok:
                started += 1
            else:
                errors.append(f"{u}: {msg}")
                self._log(msg, u, "warning")
        return started, errors

    def ready_usernames(self) -> List[str]:
        return [
            u for u, st in self.am.accounts.items()
            if st.is_active and not st.is_mailing and not st.need_relogin and st.browser
            and (st.mailing_messages or self.e.message_manager.get_messages(u))
        ]

    # ------------------------------------------------------------------ pause / close / delete
    def toggle_pause(self, usernames: List[str]) -> Tuple[int, int]:
        paused = resumed = 0
        for u in usernames:
            st = self._state(u)
            if st and st.is_active and st.is_mailing:
                st.is_paused = not st.is_paused
                if st.is_paused:
                    paused += 1
                else:
                    resumed += 1
                self._log(f"{'Paused' if st.is_paused else 'Resumed'} mailing for {u}", u)
        self.e.notify()
        return paused, resumed

    def _close_state(self, st: AccountState) -> None:
        u = st.username
        if u in self.e.task_scheduler.running_tasks:
            self.e.task_scheduler.stop_account_cycle(u)
        browser = st.browser
        st.browser = None
        st.is_active = False
        st.is_paused = False
        st.is_mailing = False
        st.need_relogin = False
        st.status_reason = ""
        if browser is not None:
            self.e.loop.run_in_executor(None, hard_close_browser, browser)

    def close(self, usernames: List[str]) -> int:
        n = 0
        for u in usernames:
            st = self._state(u)
            if st:
                self._close_state(st)
                self._log(f"Browser session ended for {u}", u)
                n += 1
        self.e.notify()
        return n

    def close_all(self) -> int:
        n = 0
        for st in list(self.am.accounts.values()):
            if st.browser or st.is_active or st.is_mailing:
                n += 1
            self._close_state(st)
        self.e.loop.run_in_executor(None, kill_orphan_chrome, self.e.config.browser_profiles_dir)
        self._log(f"All sessions closed ({n})")
        self.e.notify()
        return n

    def delete(self, usernames: List[str]) -> int:
        accounts = self.am.load_accounts()
        for u in usernames:
            st = self._state(u)
            if st:
                self._close_state(st)  # раньше браузер удалённого аккаунта оставался открытым
                del self.am.accounts[u]
            self.e.task_scheduler.chat_store.remove_user(u)
        remaining = [a for a in accounts if a.get("username") not in set(usernames)]
        self.am.save_accounts(remaining)
        self._log(f"Deleted {len(usernames)} account(s): {', '.join(usernames)}")
        self.e.notify()
        return len(usernames)

    # ------------------------------------------------------------------ accounts CRUD
    def get_account(self, username: str) -> dict:
        acc = self._account(username)
        if not acc:
            raise ActionError("Account not found")
        return dict(acc)

    def add_account(self, data: dict) -> None:
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        auth_token = (data.get("auth_token") or "").strip()
        if not username:
            raise ActionError("Username is required!")
        if not password and not auth_token:
            raise ActionError("Password or Auth Token is required!")
        acs = self.am.load_accounts()
        if any(a["username"] == username for a in acs):
            raise ActionError(f"Account with username '{username}' already exists!")
        acs.append({
            "username": username,
            "password": password,
            "proxy": (data.get("proxy") or "").strip(),
            "user_agent": (data.get("user_agent") or "").strip(),
            "group": (data.get("group") or "").strip(),
            "auth_token": auth_token,
            "ct0_token": (data.get("ct0_token") or "").strip(),
            "headless": False,
        })
        self.am.save_accounts(acs)
        self._log(f"Account added: {username}")

    def import_accounts(self, text: str) -> Tuple[int, int]:
        """Формат строки: username|auth_token|ct0_token|proxy|group (auth_token обязателен)."""
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            raise ActionError("Please enter account data!")
        acs = self.am.load_accounts()
        existing = {a["username"] for a in acs}
        added = skipped = 0
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                skipped += 1
                continue
            username, auth_token = parts[0], parts[1]
            if not username or not auth_token or username in existing:
                skipped += 1
                continue
            acs.append({
                "username": username, "password": "", "proxy": parts[3] if len(parts) > 3 else "",
                "user_agent": "", "group": parts[4] if len(parts) > 4 else "",
                "auth_token": auth_token, "ct0_token": parts[2] if len(parts) > 2 else "", "headless": False,
            })
            existing.add(username)
            added += 1
        self.am.save_accounts(acs)
        self._log(f"Import: added {added}, skipped {skipped}")
        return added, skipped

    def edit_account(self, original: str, data: dict) -> None:
        new_username = (data.get("username") or "").strip()
        if not new_username:
            raise ActionError("Username cannot be empty!")
        acs = self.am.load_accounts()
        if new_username != original and any(a["username"] == new_username for a in acs):
            raise ActionError(f"Username '{new_username}' is already taken!")
        found = False
        for a in acs:
            if a["username"] == original:
                a["username"] = new_username
                a["password"] = data.get("password", a.get("password", ""))
                a["proxy"] = (data.get("proxy") or "").strip()
                a["user_agent"] = (data.get("user_agent") or "").strip()
                a["group"] = (data.get("group") or "").strip()
                a["auth_token"] = (data.get("auth_token") or "").strip()
                a["ct0_token"] = (data.get("ct0_token") or "").strip()
                a["headless"] = False
                found = True
                break
        if not found:
            raise ActionError("Account not found")
        self.am.save_accounts(acs)
        if new_username != original and original in self.am.accounts:
            self.am.accounts[new_username] = self.am.accounts.pop(original)
            self.am.accounts[new_username].username = new_username
        self._log(f"Account updated: {original}" + (f" -> {new_username}" if new_username != original else ""))
        self.e.notify()

    def bulk_edit(self, usernames: List[str], group: Optional[str], proxies_text: Optional[str]) -> int:
        change_group = group is not None
        proxies: List[str] = []
        if proxies_text is not None:
            proxies = [p.strip() for p in proxies_text.strip().splitlines() if p.strip()]
            if not proxies:
                raise ActionError("Proxy field is checked but contains no data.")
            if len(proxies) != 1 and len(proxies) != len(usernames):
                raise ActionError(
                    f"Incorrect number of proxies ({len(proxies)}). Provide 1 proxy for all, or {len(usernames)} (one per account).")
        if not change_group and not proxies:
            raise ActionError("No action selected. Choose group and/or proxy.")
        accounts = self.am.load_accounts()
        n = 0
        for a in accounts:
            if a["username"] in usernames:
                if change_group:
                    a["group"] = group.strip()
                if proxies:
                    a["proxy"] = proxies[0] if len(proxies) == 1 else proxies[usernames.index(a["username"])]
                n += 1
        self.am.save_accounts(accounts)
        self._log(f"Bulk edit applied to {n} account(s)")
        return n
