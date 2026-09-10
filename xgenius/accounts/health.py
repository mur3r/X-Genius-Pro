"""
Здоровье браузера, статус авторизации, watchdog, аварийное закрытие (часть AccountManager).
"""

import asyncio
from typing import Dict, Optional

from selenium import webdriver

from xgenius.core import LOCK_PATHS, LOGIN_PATHS, PAGE_PROBE_JS, classify_driver_error, is_x_url
from xgenius.models import AuthStatus
from xgenius.process_utils import hard_close_browser, kill_orphan_chrome
from xgenius.settings import HEALTH_TIMEOUT_STRIKES, IDLE_HEALTH_INTERVAL


class HealthMixin:
    """Методы AccountManager: проверка браузера/сессии и восстановление после блокировок."""

    async def check_browser_health_detailed(self, browser: webdriver.Chrome) -> str:
        """
        'OK' | 'TIMEOUT' | 'CLOSED'.
        Раньше ЛЮБОЕ исключение (в т.ч. таймаут команды на перегруженном сервере)
        считалось "браузер закрыт": аккаунт уходил в inactive, а живой Chrome оставался
        висеть без управления.
        """
        if browser is None:
            return "CLOSED"
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: browser.execute_script("return document.readyState"))
            return "OK"
        except Exception as e:
            kind = classify_driver_error(e)
            if kind == "timeout":
                return "TIMEOUT"
            if kind == "closed":
                return "CLOSED"
            # прочее (например, открыт alert) — браузер жив
            self.logger.warning(f"Health-check: {type(e).__name__}: {str(e)[:120]}")
            return "OK"

    async def check_browser_health(self, browser: webdriver.Chrome) -> bool:
        """Совместимость: True, если браузер точно не закрыт (таймаут = ещё жив)."""
        return await self.check_browser_health_detailed(browser) != "CLOSED"

    def shutdown_all_browsers(self) -> None:
        """
        Раньше метод вызывался при выходе/истечении лицензии, но НЕ СУЩЕСТВОВАЛ:
        AttributeError глотался, браузеры не закрывались, chrome.exe оставались висеть
        (держали профили и грузили CPU до следующего запуска).
        """
        for username, state in list(self.accounts.items()):
            browser = state.browser
            state.browser = None
            state.is_active = False
            state.is_mailing = False
            state.is_paused = False
            if browser is not None:
                try:
                    hard_close_browser(browser, timeout=10)
                except Exception as e:
                    self.logger.error(f"Ошибка закрытия браузера: {e}", username)
        try:
            killed = kill_orphan_chrome(self.config.browser_profiles_dir)
            if killed:
                self.logger.info(f"Добиты осиротевшие процессы chrome: {killed}")
        except Exception:
            pass

    async def idle_health_watchdog(self):
        """
        Фоновая проверка браузеров, которые залогинены, но НЕ в рассылке (в рассылке
        цикл проверяет сам). Заменяет GUI.check_all_browsers(), который дергал Selenium
        из GUI-потока каждые 1.5 с для всех аккаунтов и подвешивал интерфейс.
        Три таймаута подряд = браузер считается мёртвым и закрывается принудительно.
        """
        strikes: Dict[str, int] = {}
        while True:
            try:
                await asyncio.sleep(IDLE_HEALTH_INTERVAL)
                for username, state in list(self.accounts.items()):
                    if not state.is_active or state.is_mailing or state.relogin_in_progress or not state.browser:
                        strikes.pop(username, None)
                        continue
                    status = await self.check_browser_health_detailed(state.browser)
                    if status == "OK":
                        strikes.pop(username, None)
                        continue
                    if status == "TIMEOUT":
                        strikes[username] = strikes.get(username, 0) + 1
                        if strikes[username] < HEALTH_TIMEOUT_STRIKES:
                            continue
                    self.logger.warning("Браузер не отвечает (idle watchdog). Помечаем аккаунт неактивным.", username)
                    browser = state.browser
                    state.browser = None
                    state.is_active = False
                    state.is_paused = False
                    state.status_reason = "BROWSER_CLOSED"
                    strikes.pop(username, None)
                    if browser is not None:
                        await asyncio.get_event_loop().run_in_executor(None, hard_close_browser, browser)
            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"idle watchdog error: {e}")

    async def _check_auth_state(self, browser: webdriver.Chrome) -> AuthStatus:
        """
        Проверка авторизации.

        Отличия от старой версии:
          * куки читаются ТОЛЬКО когда браузер реально на x.com. get_cookies() отдаёт куки
            текущего домена: на chrome-error:// (обрыв прокси), about:blank и т.п. auth_token
            "не находился", и аккаунт уходил в ЛОЖНЫЙ релогин;
          * вместо page_source.lower() (мегабайты на каждый вызов) — маленький JS-зонд;
          * ни один вызов Selenium не блокирует event loop.
        """
        loop = asyncio.get_event_loop()

        async def _url() -> Optional[str]:
            try:
                return await loop.run_in_executor(None, lambda: (browser.current_url or "").lower())
            except Exception:
                return None

        current_url = await _url()
        if current_url is None:
            return AuthStatus.PAGE_DOWN

        if not is_x_url(current_url):
            # Сеть/прокси/пустая вкладка — это НЕ разлогин. Пробуем вернуться домой один раз.
            self.logger.warning(f"[AUTH_CHECK] Не на x.com ({current_url[:80]}). Пробуем открыть /home.")
            try:
                await loop.run_in_executor(None, lambda: browser.get("https://x.com/home"))
                await asyncio.sleep(3)
            except Exception as e:
                if classify_driver_error(e) == "closed":
                    return AuthStatus.PAGE_DOWN
            current_url = await _url()
            if current_url is None or not is_x_url(current_url):
                self.logger.warning("[AUTH_CHECK] x.com недоступен (прокси/сеть). Считаем временным сбоем.")
                return AuthStatus.PAGE_DOWN

        if any(p in current_url for p in LOGIN_PATHS):
            self.logger.warning("[AUTH_CHECK] Обнаружен редирект на страницу входа.")
            return AuthStatus.NEED_RELOGIN

        if any(p in current_url for p in LOCK_PATHS):
            self.logger.error("[AUTH_CHECK] Обнаружен чекпоинт или блокировка аккаунта.")
            return AuthStatus.LOCKED

        try:
            cookies = await loop.run_in_executor(None, browser.get_cookies)
            has_auth_cookie = any(c.get('name') == 'auth_token' and c.get('value') for c in cookies)
        except Exception as e:
            self.logger.error(f"Ошибка получения cookies: {e}")
            return AuthStatus.PAGE_DOWN

        probe = None
        try:
            probe = await loop.run_in_executor(None, lambda: browser.execute_script(PAGE_PROBE_JS))
        except Exception:
            probe = None

        self.logger.info(f"[AUTH_CHECK] URL: {current_url[:80]} | auth_token: {has_auth_cookie}")

        if isinstance(probe, dict):
            text = probe.get("text") or ""
            if probe.get("hasLoginForm"):
                return AuthStatus.NEED_RELOGIN
            if not probe.get("conversationLoaded") and any(
                    m in text for m in ("this page is down", "something went wrong", "try reloading")):
                self.logger.warning("[AUTH_CHECK] Сбой интерфейса X (page down). Временный статус.")
                return AuthStatus.PAGE_DOWN

        if has_auth_cookie:
            return AuthStatus.OK

        self.logger.warning("[AUTH_CHECK] Кука auth_token отсутствует на x.com — требуется перелогин.")
        return AuthStatus.NEED_RELOGIN

    async def handle_lock_if_any(self, username: str) -> bool:
        state = self.accounts.get(username)
        if not state or not state.browser: 
            return True 

        # 1. Проверка блокировок
        lock_reason = await self._check_login_locks(state.browser)
        if lock_reason:
            self.logger.error(f"Аккаунт заблокирован: {lock_reason}", username)
            state.status_reason = lock_reason  
            state.is_active = False            
            state.is_mailing = False
            await self.send_telegram_error(lock_reason.split()[0], username, lock_reason)
            return True
        
        # 2. Комплексная проверка состояния
        auth_status = await self._check_auth_state(state.browser)

        if auth_status == AuthStatus.NEED_RELOGIN:
            self.logger.warning(f"Потеряна сессия. Требуется перелогин.", username)
            state.need_relogin = True
            state.status_reason = "RELOGIN"
            state.is_active = False
            state.is_mailing = False
            return True

        elif auth_status == AuthStatus.PAGE_DOWN:
            self.logger.warning(f"Страница зависла. Выполняем Soft Recovery...", username)
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, lambda: state.browser.get("https://x.com/home"))
                await asyncio.sleep(3)
            except Exception as e:
                self.logger.error(f"Ошибка при Soft Recovery: {e}")
            return False
            
        return False
    
    async def _is_on_login_page(self, browser: webdriver.Chrome) -> bool:
        loop = asyncio.get_event_loop()
        try:
            cookies = await loop.run_in_executor(None, browser.get_cookies)
            has_auth = any(c.get('name') == 'auth_token' and c.get('value') for c in cookies)
            current_url = await loop.run_in_executor(None, lambda: browser.current_url.lower())
            
            return not has_auth and ("/login" in current_url or "i/flow/login" in current_url)
        except Exception:
            return False
    
    async def check_account_health(self, username: str) -> bool:
        return not await self.handle_lock_if_any(username)
    

    async def _is_logged_in(self, browser: webdriver.Chrome) -> bool:
        """Обновленный метод для совместимости с остальным кодом"""
        status = await self._check_auth_state(browser)
        return status == AuthStatus.OK
