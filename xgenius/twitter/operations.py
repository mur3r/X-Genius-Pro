"""
TwitterOperations: пауза, сбор групп iChat, цели для ретвитов.
"""

import asyncio
import random
import re

from selenium import webdriver
from selenium.webdriver.common.by import By

from xgenius.core import CHAT_LIST_SCROLL_JS, classify_driver_error
from xgenius.logger import Logger
from xgenius.stats import StatsManager
from xgenius.text_utils import LEETSPEAK_MAP, SafeLeetspeakProcessor
from xgenius.twitter.common import accept_cookies
from xgenius.twitter.messaging import MessagingMixin
from xgenius.twitter.social import SocialMixin


class TwitterOperations(MessagingMixin, SocialMixin):

    def __init__(self, logger: Logger, stats_manager: StatsManager):
        self.logger = logger
        self.stats_manager = stats_manager
        self.leetspeak_processor = SafeLeetspeakProcessor(LEETSPEAK_MAP, self.logger)

    async def check_pause(self, account_state):
        if account_state.is_paused:
            self.logger.info("Аккаунт на паузе, ждем...", account_state.username)
        while account_state.is_paused:
            await asyncio.sleep(0.5)

async def _accept_cookies(self, browser: webdriver.Chrome) -> None:
    """Общая реализация — xgenius.twitter.common.accept_cookies."""
    await accept_cookies(browser, self.logger)

    async def find_groups(self, browser, username: str) -> set:
        """
        Открывает iChat и собирает ссылки /i/chat/g<id>. Скролл и сбор ссылок — один
        JS-вызов за шаг. Раньше на каждом из 30 шагов обходились ВСЕ элементы страницы с
        getComputedStyle() и делался отдельный HTTP-запрос get_attribute() на каждую ссылку —
        это выполнялось для каждого аккаунта перед каждой рассылкой.
        """
        groups = set()
        if not browser:
            self.logger.warning("FIND GROUPS: browser отсутствует", username)
            return groups

        loop = asyncio.get_event_loop()
        try:
            self.logger.info("Открываем iChat для сбора групп...", username)
            await loop.run_in_executor(None, lambda: browser.get("https://x.com/i/chat"))
            await asyncio.sleep(random.uniform(3, 5))
            await self._accept_cookies(browser)

            try:
                current = await loop.run_in_executor(None, lambda: browser.current_url)
            except Exception as e:
                if classify_driver_error(e) == "closed":
                    raise
                current = "?"
            self.logger.info(f"iChat URL после перехода: {current}", username)
            if "/i/chat" not in (current or ""):
                self.logger.warning("iChat не открылся (редирект). Парсинг пропущен.", username)
                return groups

            max_scrolls = 30
            no_new_rounds = 0
            for scroll_num in range(max_scrolls):
                try:
                    hrefs = await loop.run_in_executor(None, lambda: browser.execute_script(CHAT_LIST_SCROLL_JS))
                except Exception as e:
                    if classify_driver_error(e) == "closed":
                        raise
                    self.logger.warning(f"Ошибка скролла списка чатов: {type(e).__name__}", username)
                    hrefs = []

                before_count = len(groups)
                for href in hrefs or []:
                    if not href:
                        continue
                    href = str(href).split("?", 1)[0].rstrip("/")
                    match = re.search(r"https?://(?:www\.)?x\.com/i/chat/([^/?#]+)", href)
                    if not match:
                        continue
                    chat_id = match.group(1)
                    # Группа: g2035650823573876754. Личный чат: 110805057-1123456508
                    if chat_id and chat_id.startswith("g"):
                        groups.add(f"https://x.com/i/chat/{chat_id}")

                if len(groups) > before_count:
                    no_new_rounds = 0
                else:
                    no_new_rounds += 1

                self.logger.info(f"Парсинг: шаг {scroll_num + 1}/{max_scrolls}, найдено групп: {len(groups)}", username)
                await asyncio.sleep(1.0)
                if no_new_rounds >= 4:
                    break

            self.logger.info(f"Сбор iChat завершен. Найдено групп: {len(groups)}", username)
            return groups

        except Exception as e:
            self.logger.error(f"Ошибка сбора iChat-групп: {e}", username)
            return groups

    async def get_target_sender_usernames(self, browser, count: int, used_targets: set) -> list:
        forbidden = {
            "home", "explore", "notifications", "bookmarks", "participants", "profile", "settings", "lists", 
            "moments", "communities", "support", "verified", "messages", "i", "search", "connect", "compose", 
            "flows", "analytics", "monetization", "help", "topics", "trends", "privacy", "premium", "blue", 
            "professional", "safety", "tos", "rules", "verified-orgs", "developers", "about", "grok", "stream", 
            "advertise", "creator-studios", "accessibility", "account", "data", "following", "follower_requests", 
            "mentions", "retweets", "likes", "media", "highlights", "subscriptions", "spaces", "apps"
        }
        try:
            loop = asyncio.get_event_loop()
            anchors = await loop.run_in_executor(
                None, 
                lambda: browser.find_elements(
                    By.CSS_SELECTOR, 'div[data-testid="messageEntry"] a[role="link"][href^="/"]'
                )
            )
            if not anchors:
                return []
            found = set()
            for a in anchors:
                href = a.get_attribute("href")
                if href:
                    cand = href.strip("/").split("/")[-1].lower()
                    if cand and cand not in forbidden:
                        found.add(cand)
            available = list(found - used_targets)
            if len(available) < count:
                used_targets.clear()
                available = list(found)
            selected = random.sample(available, min(count, len(available)))
            used_targets.update(selected)
            return selected
        except Exception as e:
            self.logger.error(f"Не удалось извлечь имена отправителей: {str(e)}")
            return []
