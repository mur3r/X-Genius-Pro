"""
Общие помощники для страниц X: баннер cookies, подписчики.
"""

import asyncio

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


async def accept_cookies(browser: webdriver.Chrome, logger) -> None:
    """Accept cookies if consent banner is present"""
    try:
        loop = asyncio.get_event_loop()
        # Try to find and click accept cookies button
        accept_buttons = [
            "//span[contains(text(),'Accept') or contains(text(),'Accept all') or contains(text(),'Accept All')]",
            "//button[contains(text(),'Accept') or contains(text(),'Accept all') or contains(text(),'Accept All')]",
            "//div[contains(text(),'Accept') or contains(text(),'Accept all') or contains(text(),'Accept All')]",
            "//span[contains(text(),'Принять') or contains(text(),'Принять все')]",
            "//button[contains(text(),'Принять') or contains(text(),'Принять все')]",
            "//div[contains(text(),'Принять') or contains(text(),'Принять все')]"
        ]

        for xpath in accept_buttons:
            try:
                button = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 3).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                ))
                await loop.run_in_executor(None, button.click)
                logger.info("Cookies accepted")
                await asyncio.sleep(0.5)
                return
            except:
                continue

        # Try CSS selectors for common cookie banners
        css_selectors = [
            "[data-testid='cookie-accept']",
            ".cookie-accept",
            "#cookie-accept",
            "[aria-label*='Accept']",
            "[aria-label*='accept']"
        ]

        for selector in css_selectors:
            try:
                button = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                ))
                await loop.run_in_executor(None, button.click)
                logger.info("Cookies accepted via CSS selector")
                await asyncio.sleep(0.5)
                return
            except:
                continue

    except Exception as e:
        logger.debug(f"Cookie acceptance failed or not needed: {e}")



async def new_get_followers_count(browser, username: str) -> str:
    loop = asyncio.get_event_loop()
    
    # Функция для выполнения синхронных действий с Selenium в отдельном потоке
    def _fetch_followers():
        # Переходим на страницу пользователя
        browser.get(f"https://x.com/{username}")
        
        # Ждем появления нужного элемента прямо внутри потока выполнения Selenium,
        # чтобы гарантировать работу с тем же драйвером без разрыва контекста
        a_elem = WebDriverWait(browser, 15).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'verified_followers')]"))
        )
        return a_elem.text

    try:
        # Небольшая пауза перед началом работы с браузером
        await asyncio.sleep(1)
        
        # Запускаем всю цепочку (переход + ожидание) в executor, 
        # чтобы не блокировать основной асинхронный цикл приложения
        result = await loop.run_in_executor(None, _fetch_followers)
        return result
        
    except Exception as e:
        # Перехватываем ошибки (например, если элемент не найден или тайм-аут вышел)
        print(f"Error fetching followers for {username}: {e}")
        return "N/A"
