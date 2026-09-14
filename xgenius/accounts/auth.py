"""
Вход в аккаунт: куки -> токены -> пароль, автоперелогин (часть AccountManager).
"""

import asyncio
import random
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from xgenius.cookies import load_cookies, log_account_to_file, save_cookies
from xgenius.core import classify_driver_error
from xgenius.models import AccountCredentials, AccountState
from xgenius.process_utils import hard_close_browser
from xgenius.text_utils import escape_markdown
from xgenius.twitter.common import accept_cookies


class AuthMixin:
    """Методы AccountManager: login_account, _perform_login, auto_relogin_if_needed."""

    async def _finalize_login(self, account_state: AccountState, credentials: AccountCredentials,
                              browser: webdriver.Chrome, how: str,
                              fetch_followers: bool, notify: bool, persist_cookies: bool) -> None:
        """Общий хвост успешного входа (раньше был скопирован в трёх ветках login_account)."""
        loop = asyncio.get_event_loop()
        account_state.is_active = True
        account_state.need_relogin = False
        account_state.status_reason = ""
        account_state.last_action_time = datetime.now()
        self.logger.info(f"Вход выполнен ({how})", credentials.username)

        bot_instance = self.gui_instance.telegram_bot_instance if self.gui_instance and getattr(self.gui_instance, 'telegram_bot_instance', None) else None
        pc_id = bot_instance.config.pc_id if bot_instance and getattr(bot_instance, 'config', None) else None

        if persist_cookies:
            try:
                await loop.run_in_executor(
                    None, lambda: save_cookies(browser, self.config, credentials.username,
                                               bot_instance.db_manager if bot_instance else None, pc_id))
            except Exception as e:
                self.logger.error(f"Не удалось сохранить куки: {e}", credentials.username)

        auth_token, ct0_token = await self.get_auth_tokens(browser)
        if auth_token:
            account_state.auth_token = auth_token
        if ct0_token:
            account_state.ct0_token = ct0_token

        if fetch_followers:
            # Тяжёлая операция (переход на профиль): при автоперелогине пропускаем
            account_state.followers_count = await self.get_followers_count(browser, credentials.username)
            try:
                await loop.run_in_executor(None, lambda: browser.get("https://x.com/home"))
            except Exception:
                pass
        followers_count = account_state.followers_count

        if auth_token or ct0_token:
            if bot_instance:
                try:
                    bot_instance.db_manager.update_tokens(pc_id, credentials.username, auth_token or '', ct0_token or '')
                    bot_instance.db_manager.update_followers_count(pc_id, credentials.username, followers_count)
                except Exception as e:
                    self.logger.error(f"Не удалось обновить БД бота: {e}", credentials.username)
            try:
                accounts_data = self.load_accounts()
                changed = False
                for acc in accounts_data:
                    if acc.get('username') == credentials.username:
                        if acc.get('auth_token') != (auth_token or '') or acc.get('ct0_token') != (ct0_token or ''):
                            acc['auth_token'] = auth_token or ''
                            acc['ct0_token'] = ct0_token or ''
                            changed = True
                        break
                if changed:
                    self.save_accounts(accounts_data)
                    self.logger.info("Токены сохранены в accounts.json", credentials.username)
            except Exception as e:
                self.logger.error(f"Не удалось сохранить токены в accounts.json: {e}", credentials.username)

        if notify and bot_instance and getattr(bot_instance, 'running', False):
            safe_auth = escape_markdown(auth_token) if auth_token else 'НЕ ПОЛУЧЕН'
            safe_ct0 = escape_markdown(ct0_token) if ct0_token else 'НЕ ПОЛУЧЕН'
            safe_proxy = credentials.proxy if credentials.proxy else 'не передано'
            safe_username = escape_markdown(credentials.username)
            title = "ВОЙДЕНО ПО ТОКЕНАМ" if how == "tokens" else "ПОЛУЧЕНЫ ТОКЕНЫ"
            token_msg = f"""🔑 *{title}*
📌 *Аккаунт:* @{safe_username}
🔐 *Auth Token:* `{safe_auth}`
🛡️ *CT0 Token:* `{safe_ct0}`
🌐 *Прокси:* `{safe_proxy}`
👥 *Подписчики:* `{followers_count}`
💬 *Чатов:* `{len(account_state.groups)}`
⏰ *Время:* `{datetime.now().strftime('%H:%M:%S')}`"""
            try:
                asyncio.create_task(bot_instance.send_message(token_msg))
            except Exception:
                pass
            log_account_to_file(
                credentials.username,
                credentials.password or '',
                credentials.proxy or '',
                auth_token or '',
                ct0_token or '',
                len(account_state.groups),
                followers_count
            )

    async def login_account(self, credentials: AccountCredentials, fetch_followers: bool = True,
                            notify: bool = True) -> None:
        """
        Вход в аккаунт. fetch_followers/notify=False используется при автоматическом
        перелогине/восстановлении браузера (не гоняем профиль, не спамим в Telegram).
        Порядок: сессия из профиля Chrome (--user-data-dir) / куки -> токены -> пароль.
        """
        if credentials.username not in self.accounts:
            self.accounts[credentials.username] = AccountState(username=credentials.username)
            self.accounts[credentials.username].groups = self.load_saved_groups(credentials.username)
        account_state = self.accounts[credentials.username]

        account_state.need_relogin = False
        account_state.status_reason = ""
        account_state.parked = False

        loop = asyncio.get_event_loop()

        # Старый Chrome этого аккаунта (после неудачного входа/обрыва) держит профиль:
        # новый браузер на том же --user-data-dir не стартует. Закрываем принудительно.
        stale = account_state.browser
        if stale is not None:
            account_state.browser = None
            await loop.run_in_executor(None, hard_close_browser, stale)

        browser = None
        try:
            browser = await self.browser_manager.create_browser(credentials)
            account_state.browser = browser
            try:
                account_state.humanizer.set_browser(browser)
            except Exception:
                pass

            bot_instance = self.gui_instance.telegram_bot_instance if self.gui_instance and getattr(self.gui_instance, 'telegram_bot_instance', None) else None
            pc_id = bot_instance.config.pc_id if bot_instance and getattr(bot_instance, 'config', None) else None
            try:
                await loop.run_in_executor(
                    None, lambda: load_cookies(browser, self.config, credentials.username,
                                               bot_instance.db_manager if bot_instance else None, pc_id))
            except Exception as e:
                self.logger.warning(f"Куки не загружены: {e}", credentials.username)

            # 1. Уже залогинены (профиль Chrome / куки из файла)
            try:
                await loop.run_in_executor(None, lambda: browser.get("https://x.com/home"))
                await asyncio.sleep(2)
            except Exception as e:
                if classify_driver_error(e) == "closed":
                    raise
            if await self._is_logged_in(browser):
                await self._finalize_login(account_state, credentials, browser, "cookies",
                                           fetch_followers, notify, persist_cookies=False)
                return

            # 2. Токены
            if credentials.auth_token:
                self.logger.info("Сессии нет, пробуем войти по токенам", credentials.username)
                try:
                    await self._login_with_tokens(browser, credentials)
                    if await self._is_logged_in(browser):
                        await self._finalize_login(account_state, credentials, browser, "tokens",
                                                   fetch_followers, notify, persist_cookies=True)
                        return
                    self.logger.warning("Токены не приняты X (auth_token устарел?)", credentials.username)
                except Exception as e:
                    self.logger.error(f"Не удалось войти по токенам: {e}", credentials.username)

            # 3. Пароль
            if not credentials.password:
                raise Exception("Сессия недействительна, а пароля нет — нужен новый auth_token")
            await self._perform_login(browser, credentials)
            if await self._is_logged_in(browser):
                await self._finalize_login(account_state, credentials, browser, "password",
                                           fetch_followers, notify, persist_cookies=True)
                return
            raise Exception("Не удалось войти в аккаунт")

        except Exception as e:
            self.logger.error(f"Ошибка входа: {str(e)}", credentials.username)
            account_state.is_active = False
            # При автоматическом входе (notify=False) неуправляемый Chrome не оставляем.
            # При ручном Login окно оставляем открытым — оператор может решить капчу/код.
            if not notify and browser is not None and account_state.browser is browser:
                account_state.browser = None
                await loop.run_in_executor(None, hard_close_browser, browser)
            raise Exception(f"Ошибка входа: {str(e)}")

async def _accept_cookies(self, browser: webdriver.Chrome) -> None:
    """Общая реализация — xgenius.twitter.common.accept_cookies."""
    await accept_cookies(browser, self.logger)

    async def _perform_login(self, browser: webdriver.Chrome, credentials: AccountCredentials) -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: browser.get("https://x.com/login"))
            await asyncio.sleep(2)

            # Accept cookies if present
            await self._accept_cookies(browser)
            
            if credentials.username in self.accounts:
                self.accounts[credentials.username].status_reason = ""
                self.accounts[credentials.username].need_relogin = False

            if await self._is_logged_in(browser):
                self.logger.info("Уже залогинен", credentials.username)
                return

            self.logger.info("Заполняем логин...", credentials.username)
            username_field = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 15).until(
                EC.presence_of_element_located((By.NAME, "text"))
            ))
            await loop.run_in_executor(None, username_field.clear)
            for char in credentials.username:
                await loop.run_in_executor(None, lambda: username_field.send_keys(char))
                await asyncio.sleep(random.uniform(0.05, 0.15))
            
            self.logger.info("Нажимаем Далее...", credentials.username)
            next_button = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'Next') or contains(text(),'Далее')]"))
            ))
            await loop.run_in_executor(None, next_button.click)
            await asyncio.sleep(1)
            
            lock_status = await self._check_login_locks(browser)
            if lock_status:
                await self.send_telegram_error(lock_status.split()[0], credentials.username, lock_status)
                raise Exception(lock_status)

            self.logger.info("Заполняем пароль...", credentials.username)
            try:
                password_field = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 15).until(
                    EC.presence_of_element_located((By.NAME, "password"))
                ))
            except Exception:
                lock_status = await self._check_login_locks(browser)
                if lock_status:
                    await self.send_telegram_error(lock_status.split()[0], credentials.username, lock_status)
                    raise Exception(lock_status)
                raise Exception("Поле пароля не найдено")

            await loop.run_in_executor(None, password_field.clear)
            for char in credentials.password:
                await loop.run_in_executor(None, lambda: password_field.send_keys(char))
                await asyncio.sleep(random.uniform(0.05, 0.15))
            
            self.logger.info("Нажимаем Войти...", credentials.username)
            login_button = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'Log in') or contains(text(),'Войти')]"))
            ))
            await loop.run_in_executor(None, login_button.click)
            
            for _ in range(12):
                await asyncio.sleep(2.5)
                if await self._is_logged_in(browser):
                    self.logger.info("Логин успешен!", credentials.username)
                    return
                
                lock_status = await self._check_login_locks(browser)
                if lock_status:
                    if credentials.username in self.accounts:
                        self.accounts[credentials.username].status_reason = lock_status
                    await self.send_telegram_error(lock_status.split()[0], credentials.username, lock_status)
                    raise Exception(lock_status)

            self.logger.error("Проверка входа не удалась после нескольких попыток", credentials.username)
            raise Exception("Проверка входа не удалась (Таймаут)")
            
        except Exception as e:
            error_text = str(e)
            if credentials.username in self.accounts:
                if not self.accounts[credentials.username].status_reason:
                     self.accounts[credentials.username].status_reason = "Error"
                     
                if "SUSPENDED" in error_text: 
                    self.accounts[credentials.username].status_reason = "SUSPENDED"
                    await self.send_telegram_error("SUSPENDED", credentials.username, error_text)
                elif "EMAIL" in error_text: 
                    self.accounts[credentials.username].status_reason = "EMAIL LOCK"
                    await self.send_telegram_error("EMAIL_LOCK", credentials.username, error_text)
                elif "LOCKED" in error_text: 
                    self.accounts[credentials.username].status_reason = "LOCKED"
                    await self.send_telegram_error("LOCKED", credentials.username, error_text)
                elif "PROXY" in error_text.upper() or "ERR_PROXY" in error_text.upper() or "proxy" in error_text.lower():
                    self.accounts[credentials.username].status_reason = "PROXY CHANGE"
                    await self.send_telegram_error("PROXY_CHANGE", credentials.username, error_text)
                elif "WinError 10061" in error_text or "connection" in error_text.lower():
                    self.accounts[credentials.username].status_reason = "PROXY CHANGE"
                    await self.send_telegram_error("PROXY_CHANGE", credentials.username, error_text)

            self.logger.error(f"Процесс входа не удался: {error_text}", credentials.username)
            raise Exception(f"Процесс входа не удался: {error_text}")

    async def _check_login_locks(self, browser: webdriver.Chrome) -> Optional[str]:
        try:
            loop = asyncio.get_event_loop()
            
            try:
                current_url = await loop.run_in_executor(None, lambda: browser.current_url.lower())
            except Exception as e:
                if classify_driver_error(e) == "closed":
                    return "BROWSER CLOSED"
                return None

            # --- 1. ЖЕЛЕЗНЫЕ ПРОВЕРКИ ПО URL (Это 100% блокировки) ---
            if "/account/access" in current_url: return "LOCKED (CAPTCHA)"
            if "/account/suspended" in current_url: return "SUSPENDED"
            if "/login_challenge" in current_url: return "EMAIL CODE"
            if "consent_violation_flow" in current_url: return "CONSENT LOCK"
            if "denied" in current_url: return "ACCESS DENIED"

            # --- 2. ЗАЩИТА ОТ ЛОЖНЫХ СРАБАТЫВАНИЙ ---
            # Если мы успешно сидим в ленте или сообщениях, то текст на экране — это скорее всего твиты.
            # Мы НЕ проверяем текст страницы, если URL "нормальный".
            if "/home" in current_url or "/messages" in current_url:
                return None

            # --- 3. ТОЧЕЧНАЯ ПРОВЕРКА ЭЛЕМЕНТОВ (А не просто текст в коде) ---
            try:
                # Проверка капчи Arkose (ищем именно iframe, а не просто слово в коде)
                arkose_frame = await loop.run_in_executor(None, lambda: browser.find_elements(By.XPATH, "//iframe[contains(@src, 'arkose')]"))
                if arkose_frame:
                    # Проверяем, виден ли он (иногда он есть в коде, но скрыт)
                    is_visible = await loop.run_in_executor(None, lambda: arkose_frame[0].is_displayed())
                    if is_visible:
                        return "LOCKED (CAPTCHA)"

                # Видимый текст вместо page_source (мегабайты HTML на каждую проверку)
                page_source = await loop.run_in_executor(None, lambda: browser.execute_script(
                    "return ((document.body && document.body.innerText) || '').slice(0, 20000).toLowerCase();"))
                
                # Проверки текста делаем только если URL странный (не home/messages)
                if "suspended due to a policy violation" in page_source: return "SUSPENDED"
                if "account has been suspended" in page_source: return "SUSPENDED"
                if "действие учетной записи приостановлено" in page_source: return "SUSPENDED"
                
                # Проверка на поле ввода кода почты (строгая)
                if "confirmation code" in page_source and "email" in page_source: 
                     # Проверяем, есть ли поле ввода
                     if await loop.run_in_executor(None, lambda: browser.find_elements(By.NAME, "verif_code")):
                        return "EMAIL CODE"

            except Exception:
                pass
            
            return None
        except Exception:
            return None

    async def auto_relogin_if_needed(self, username: str, force: bool = False) -> bool:
        """
        Пересоздаёт браузер и заново входит в аккаунт.
        force=True — не проверять, "нужен ли релогин" (используется при BROWSER_CLOSED:
        браузер умер, но сессия в профиле Chrome обычно жива — вход проходит по кукам).
        """
        state = self.accounts.get(username)
        if not state:
            return False

        if state.relogin_in_progress:
            self.logger.info(f"Перелогин для {username} уже выполняется, ждём результат", username)
            for _ in range(180):
                await asyncio.sleep(1)
                if not state.relogin_in_progress:
                    updated_state = self.accounts.get(username)
                    return bool(updated_state and updated_state.browser and not updated_state.need_relogin)
            return False

        if not force:
            needs_relogin = state.need_relogin
            if not needs_relogin and state.browser:
                try:
                    needs_relogin = await self._is_on_login_page(state.browser)
                except Exception:
                    needs_relogin = False
            if not needs_relogin:
                return True

        state.relogin_in_progress = True
        state.status_reason = "RECOVERING"
        loop = asyncio.get_event_loop()
        try:
            self.logger.info(f"Начинаем автоматический перелогин для {username}", username)

            old_browser = state.browser
            state.browser = None
            if old_browser is not None:
                # quit() + добить дерево chrome, иначе новый браузер не откроет занятый профиль
                await loop.run_in_executor(None, hard_close_browser, old_browser)
                await asyncio.sleep(2)

            accounts = self.load_accounts()
            account_data = next((acc for acc in accounts if acc.get("username") == username), None)
            if not account_data:
                self.logger.error(f"Не найдены данные аккаунта для {username}", username)
                state.need_relogin = True
                return False

            credentials = AccountCredentials(
                username=account_data["username"],
                password=account_data.get("password", ""),
                proxy=account_data.get("proxy"),
                user_agent=account_data.get("user_agent"),
                headless=account_data.get("headless", False),
                group=account_data.get("group", ""),
                auth_token=account_data.get("auth_token"),
                ct0_token=account_data.get("ct0_token")
            )

            await self.login_account(credentials, fetch_followers=False, notify=False)

            new_state = self.accounts.get(username)
            if not new_state or not new_state.browser:
                raise Exception("После перелогина браузер или state отсутствует")

            new_state.need_relogin = False
            new_state.status_reason = ""
            self.logger.info(f"Автоматический перелогин успешен для {username}", username)
            return True

        except Exception as e:
            curr_state = self.accounts.get(username, state)
            curr_state.need_relogin = True
            curr_state.status_reason = "RELOGIN FAILED"
            self.logger.error(f"Автоматический перелогин не удался для {username}: {e}", username)
            return False

        finally:
            curr_state = self.accounts.get(username, state)
            if curr_state:
                curr_state.relogin_in_progress = False

    async def _login_with_tokens(self, browser: webdriver.Chrome, credentials: AccountCredentials) -> None:
        """Login using auth_token and ct0 tokens directly"""
        try:
            loop = asyncio.get_event_loop()
            
            # Открываем x.com
            await loop.run_in_executor(None, lambda: browser.get("https://x.com"))
            await asyncio.sleep(2)
            
            # Устанавливаем куки с токенами
            if credentials.auth_token:
                auth_cookie = {
                    'name': 'auth_token',
                    'value': credentials.auth_token,
                    'domain': '.x.com',
                    'path': '/',
                    'secure': True,
                    'httpOnly': False
                }
                try:
                    browser.add_cookie(auth_cookie)
                    self.logger.info("Auth token cookie added", credentials.username)
                except Exception as e:
                    self.logger.error(f"Failed to add auth_token cookie: {e}", credentials.username)
            
            if credentials.ct0_token:
                ct0_cookie = {
                    'name': 'ct0',
                    'value': credentials.ct0_token,
                    'domain': '.x.com',
                    'path': '/',
                    'secure': True,
                    'httpOnly': False
                }
                try:
                    browser.add_cookie(ct0_cookie)
                    self.logger.info("CT0 token cookie added", credentials.username)
                except Exception as e:
                    self.logger.error(f"Failed to add ct0 cookie: {e}", credentials.username)
            
            # Перезагружаем страницу, чтобы применить куки
            await loop.run_in_executor(None, lambda: browser.get("https://x.com"))
            await asyncio.sleep(2)
            
            # Принимаем куки, если появился баннер
            await self._accept_cookies(browser)
            
            self.logger.info("Токены установлены, проверяем вход...", credentials.username)
            
        except Exception as e:
            self.logger.error(f"Ошибка при входе по токенам: {e}", credentials.username)
            raise
