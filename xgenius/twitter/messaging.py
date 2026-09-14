"""
Отправка сообщения в чат: зонд страницы, человеческий набор, кнопка Send, GIF.
"""

import asyncio
import random
import time
from typing import Optional

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from human1 import Humanizer

from xgenius.core import (
    BROWSER_CLOSED,
    LIMIT_REACHED,
    LOCKED,
    NEED_RELOGIN,
    NO_INPUT,
    OK_TO_TYPE,
    PAGE_PROBE_JS,
    RETRY,
    SUCCESS,
    chat_id_from_url,
    classify_driver_error,
    classify_page,
    normalize_for_compare,
    split_for_typing,
    toasts_indicate_limit,
)
from xgenius.models import AccountState
from xgenius.settings import COMPOSER_WAIT_SECONDS, SEND_VERIFY_SECONDS, TYPING_MAX_SECONDS


def _typing_summary(st: dict) -> str:
    """Короткая сводка набора для лога: сколько набрано, за сколько, задержки клавиш."""
    elapsed = time.monotonic() - st["started"]
    avg = st["sum_ms"] / st["typed"] if st["typed"] else 0.0
    s = (f"{st['typed']}/{st['total']} порций за {elapsed:.1f}с "
         f"(ср. {avg:.0f} мс/клавишу, макс {st['max_ms'] / 1000:.1f}с)")
    if st["refinds"]:
        s += f", поле ввода пересоздавалось {st['refinds']} раз"
    if st["fallback_at"] is not None:
        s += f", остаток с {st['fallback_at']}-й порции вставлен целиком"
    return s


class MessagingMixin:
    """Методы TwitterOperations: send_message и всё, что ей нужно."""

    # ------------------------------------------------------------------
    # Ввод текста ("мультиком"): человеческий набор + безопасная вставка emoji.
    # Старые _fill_message_reliably и _simulate_typing удалены: их никто не вызывал.
    # ------------------------------------------------------------------
    COMPOSER_XPATH = (
        "//textarea[@data-testid='dm-composer-textarea'] | "
        "//textarea[@placeholder='Message' or @aria-label='Message'] | "
        "//*[@data-testid='dmComposerTextInput'] | "
        "//textarea"
    )

    async def _probe_page(self, browser) -> Optional[dict]:
        """Маленький JS-зонд состояния страницы чата (см. PAGE_PROBE_JS)."""
        loop = asyncio.get_event_loop()
        try:
            probe = await loop.run_in_executor(None, lambda: browser.execute_script(PAGE_PROBE_JS))
            return probe if isinstance(probe, dict) else None
        except Exception as e:
            if classify_driver_error(e) == "closed":
                raise
            return None

    def _find_composer_sync(self, browser):
        return browser.find_element(By.XPATH, self.COMPOSER_XPATH)

    def _clear_composer_sync(self, browser, box) -> None:
        try:
            browser.execute_script("arguments[0].focus();", box)
        except Exception:
            pass
        try:
            box.click()
        except Exception:
            pass
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)

    @staticmethod
    def new_typing_stats(total: int = 0) -> dict:
        return {"total": total, "typed": 0, "started": time.monotonic(), "sum_ms": 0.0, "max_ms": 0.0,
                "refinds": 0, "fallback_at": None}

    def _type_message_sync(self, browser, text: str, humanizer: Optional[Humanizer], should_stop=None,
                           stats: Optional[dict] = None) -> bool:
        """
        Набирает текст как человек. Выполняется целиком в одном потоке executor'а,
        чтобы не дергать event loop на каждый символ.

        Почему старый "мультиком" не работал:
          * Humanizer.simulate_typing из human1.py вообще не вызывался (и enabled=False);
          * ветка посимвольного send_keys падала на первом же emoji вне BMP
            ("ChromeDriver only supports characters in the BMP") — вся отправка
            уходила в FAILED.
        Здесь BMP-символы (буквы, ☭ 卐 ♫ ✰ ...) идут как реальные нажатия клавиш,
        а emoji/склейки — через CDP Input.insertText (для React это обычный ввод).

        Диагностика «сообщение набирается не полностью» (ТЗ, п. 1): каждая клавиша — это
        HTTP-запрос к chromedriver, и на перегруженном сервере он может идти секунды.
        В `stats` копится число набранных порций и задержки клавиш — они попадают в лог
        независимо от того, чем закончился набор. Два известных обрыва набора:
          * React перерисовал композер (пришло новое сообщение в группу) — элемент
            «протух» (StaleElementReference); теперь поле ищется заново и набор
            продолжается с той же позиции, а не падает в RETRY с половиной текста в поле;
          * набор идёт дольше TYPING_MAX_SECONDS — остаток вставляется одним куском,
            чтобы сообщение ушло целиком, а не осталось недописанным.
        """
        chunks = split_for_typing(text)
        if stats is None:
            stats = self.new_typing_stats(len(chunks))
        else:
            stats["total"] = len(chunks)
            stats["started"] = time.monotonic()
        box = self._find_composer_sync(browser)
        self._clear_composer_sync(browser, box)
        time.sleep(0.3)

        if humanizer is not None and getattr(humanizer, "enabled", False):
            speed = humanizer.get_typing_speed()
            typo_chance = humanizer.typo_chance
            word_pause_chance = humanizer.word_pause_chance
            word_pause_range = humanizer.word_pause_range
            correction_delay = humanizer.correction_delay
        else:
            speed = (0.03, 0.09)
            typo_chance = 0.0
            word_pause_chance = 0.0
            word_pause_range = (0.0, 0.0)
            correction_delay = (0.3, 0.6)

        def press(kind: str, payload: str) -> None:
            nonlocal box
            for attempt in (1, 2):
                try:
                    if kind == "newline":
                        box.send_keys(Keys.SHIFT, Keys.ENTER)
                    elif kind == "insert":
                        browser.execute_cdp_cmd("Input.insertText", {"text": payload})
                    else:
                        ch = payload
                        if typo_chance and ch.isalpha() and random.random() < typo_chance:
                            typo = humanizer._get_typo_char(ch)
                            if typo != ch:
                                box.send_keys(typo)
                                time.sleep(random.uniform(*correction_delay))
                                box.send_keys(Keys.BACKSPACE)
                        box.send_keys(ch)
                    return
                except StaleElementReferenceException:
                    if attempt == 2:
                        raise
                    # X перерисовал композер — берём новый элемент и повторяем ту же порцию
                    stats["refinds"] += 1
                    box = self._find_composer_sync(browser)
                    try:
                        browser.execute_script("arguments[0].focus();", box)
                    except Exception:
                        pass

        for i, (kind, payload) in enumerate(chunks):
            if should_stop is not None and should_stop():
                return False

            if TYPING_MAX_SECONDS and time.monotonic() - stats["started"] > TYPING_MAX_SECONDS:
                # Сервер не тянет посимвольный набор — дописываем остаток одним куском
                rest = "".join(p for _, p in chunks[i:])
                stats["fallback_at"] = i
                t0 = time.monotonic()
                press("insert", rest)
                stats["typed"] = len(chunks)
                stats["max_ms"] = max(stats["max_ms"], (time.monotonic() - t0) * 1000.0)
                return True

            t0 = time.monotonic()
            press(kind, payload)
            ms = (time.monotonic() - t0) * 1000.0
            stats["typed"] += 1
            stats["sum_ms"] += ms
            if ms > stats["max_ms"]:
                stats["max_ms"] = ms

            delay = random.uniform(*speed)
            if payload in ".!?,:;":
                delay += random.uniform(0.2, 0.5)
            elif payload == " " and word_pause_chance and random.random() < word_pause_chance:
                delay += random.uniform(*word_pause_range)
            time.sleep(delay)
        return True

    def _insert_text_fallback_sync(self, browser, text: str) -> None:
        """Запасной вариант: очистить поле и вставить весь текст через CDP одним куском
        (эквивалент вставки из буфера, но без глобального clipboard, за который
        раньше конкурировали все аккаунты через CLIPBOARD_LOCK)."""
        box = self._find_composer_sync(browser)
        self._clear_composer_sync(browser, box)
        time.sleep(0.2)
        browser.execute_cdp_cmd("Input.insertText", {"text": text})

    async def _select_gif(self, browser, username: str, account_state, humanize: bool):
        try:
            loop = asyncio.get_event_loop()
            self.logger.info("Внутри _select_gif", username)
            await self.check_pause(account_state)
            gif_button = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='Add a GIF']"))
            ))
            await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView(true);", gif_button))
            await asyncio.sleep(1)
            await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", gif_button))
            await asyncio.sleep(1)
            if humanize and account_state and account_state.humanizer:
                self.logger.info("Симулируем выбор GIF через humanizer", username)
                await loop.run_in_executor(None, account_state.humanizer.simulate_gif_selection, None)
            categories = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#layers div.css-175oi2r.r-18u37iz.r-1mnahxq > button[role='button']"))
            ))
            self.logger.info(f"Найдено {len(categories)} категорий GIF", username)
            if categories:
                random_category = random.choice(categories)
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView(true);", random_category))
                await asyncio.sleep(1.5)
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", random_category))
                await asyncio.sleep(1)
                gifs = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button.css-175oi2r.r-1wbh5a2.r-1pdvg5x"))
                ))
                self.logger.info(f"Найдено {len(gifs)} элементов GIF", username)
                if gifs:
                    random_gif = random.choice(gifs)
                    await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView(true);", random_gif))
                    await asyncio.sleep(1.5)
                    await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", random_gif))
                    await asyncio.sleep(1)
                    self.logger.info(f"GIF добавлен в {browser.current_url}", username)
                else:
                    self.logger.error("GIF не найдены", username)
            else:
                self.logger.error("Категории GIF не найдены", username)
        except Exception as gif_error:
            self.logger.error(f"Ошибка выбора GIF: {str(gif_error)}", username)
            



    async def _send_message_button(self, browser, username: str, chat_id: str = "") -> tuple:
        """
        Отправляет набранное сообщение: click -> JS click -> Enter; после каждой попытки
        подтверждаем отправку зондом. Возвращает (ok, reason):
          reason: "" | "limit" (тост о лимите) | "navigated" (X увёл с чата) | "unconfirmed".
        Раньше "textarea исчезла" считалось успехом: на странице ошибки X она тоже
        исчезает, и неотправленные сообщения засчитывались как SUCCESS.
        """
        loop = asyncio.get_event_loop()
        send_btn_xpath = (
            "//button[@data-testid='dmComposerSendButton'] | "
            "//div[@data-testid='dmComposerSendButton'] | "
            "//button[@aria-label='Send' or @aria-label='Отправить'] | "
            "//div[@role='button'][@aria-label='Send' or @aria-label='Отправить']"
        )

        async def verify() -> str:
            deadline = time.monotonic() + SEND_VERIFY_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                probe = await self._probe_page(browser)
                if not probe:
                    continue
                if toasts_indicate_limit(probe):
                    return "limit"
                url = (probe.get("url") or "").lower()
                if chat_id and chat_id not in url:
                    return "navigated"
                if probe.get("hasComposer") and not (probe.get("composerValue") or "").strip():
                    return "sent"
            return "unconfirmed"

        def click_send():
            btn = WebDriverWait(browser, 5).until(EC.element_to_be_clickable((By.XPATH, send_btn_xpath)))
            if btn.get_attribute("disabled") is not None or btn.get_attribute("aria-disabled") == "true":
                self.logger.warning("Кнопка Send отключена (React не принял текст?)", username)
                return False
            btn.click()
            return True

        def js_click_send():
            btn = browser.find_element(By.XPATH, send_btn_xpath)
            browser.execute_script("arguments[0].click();", btn)
            return True

        def press_enter():
            box = self._find_composer_sync(browser)
            box.send_keys(Keys.RETURN)
            return True

        for name, fn in (("click", click_send), ("js-click", js_click_send), ("enter", press_enter)):
            try:
                ok = await loop.run_in_executor(None, fn)
            except Exception as e:
                if classify_driver_error(e) == "closed":
                    raise
                self.logger.warning(f"Отправка через {name} не удалась: {type(e).__name__}: {str(e)[:100]}", username)
                ok = False
            if not ok:
                continue
            result = await verify()
            if result == "sent":
                self.logger.info(f"✅ Отправка подтверждена ({name}).", username)
                return True, ""
            if result in ("limit", "navigated"):
                self.logger.warning(f"Отправка ({name}): {result}", username)
                return False, result
            self.logger.warning(f"⚠️ {name}: отправка не подтверждена, пробуем следующий способ.", username)

        # Последний взгляд: поле пустое и мы всё ещё в чате — считаем отправленным
        probe = await self._probe_page(browser)
        if probe and probe.get("hasComposer") and not (probe.get("composerValue") or "").strip() \
                and (not chat_id or chat_id in (probe.get("url") or "").lower()):
            self.logger.info("✅ Поле пустое после попыток — считаем отправленным.", username)
            return True, ""
        self.logger.error("❌ Не удалось подтвердить отправку ни одним способом.", username)
        return False, "unconfirmed"


    async def send_message(self, state: AccountState, group_url: str, message_text: str, humanize: bool = True) -> str:
        """
        Отправляет сообщение в группу iChat. Ни один вызов Selenium не блокирует event loop
        (раньше browser.get()/send_keys/page_source вызывались синхронно: на время загрузки
        страницы одним аккаунтом замирали ВСЕ аккаунты и GUI).

        Статусы: SUCCESS, RETRY (временно, группа вернётся в очередь), NO_INPUT (чат загружен,
        поля ввода нет), NEED_RELOGIN, LOCKED, BROWSER_CLOSED, LIMIT_REACHED.
        """
        browser = state.browser
        username = state.username
        if not browser:
            return BROWSER_CLOSED
        loop = asyncio.get_event_loop()
        chat_id = chat_id_from_url(group_url)

        t_start = time.monotonic()
        try:
            # 1. Переход в чат
            try:
                await loop.run_in_executor(None, lambda: browser.get(group_url))
            except Exception as e:
                kind = classify_driver_error(e)
                if kind == "closed":
                    return BROWSER_CLOSED
                self.logger.warning(
                    f"Переход в {group_url} не удался за {time.monotonic() - t_start:.1f}с "
                    f"({type(e).__name__}): {str(e)[:120]}", username)
                if kind != "timeout":
                    return RETRY
                # таймаут загрузки: страница могла частично отрисоваться — проверим зондом
            state.parked = False  # мы снова на x.com (после отдыха браузер мог стоять на about:blank)
            t_loaded = time.monotonic()

            # 2. Ждём поле ввода, классифицируя состояние страницы
            verdict, reason = RETRY, "no probe"
            deadline = time.monotonic() + COMPOSER_WAIT_SECONDS
            while True:
                probe = await self._probe_page(browser)
                verdict, reason = classify_page(probe, chat_id)
                if verdict != RETRY or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(1.0)
            t_ready = time.monotonic()
            # Тайминги загрузки: по ним видно, прокси это (get долгий) или CPU (композер долго не появляется)
            self.logger.info(
                f"⏱ чат открыт за {t_loaded - t_start:.1f}с, поле ввода через {t_ready - t_loaded:.1f}с "
                f"({verdict}{': ' + reason if reason else ''})", username)

            if verdict == NEED_RELOGIN:
                self.logger.warning("Обнаружена страница входа.", username)
                return NEED_RELOGIN
            if verdict == LOCKED:
                self.logger.error(f"Чекпоинт/блокировка: {reason}", username)
                return LOCKED
            if verdict == NO_INPUT:
                self.logger.warning(f"Нет поля ввода в {group_url}: {reason}", username)
                return NO_INPUT
            if verdict != OK_TO_TYPE:
                self.logger.warning(f"Чат {group_url} не готов: {reason}", username)
                return RETRY

            await asyncio.sleep(random.uniform(1.0, 2.5))

            # 3. Набор текста
            humanizer = state.humanizer if humanize else None
            if humanizer is not None:
                humanizer.enabled = True
            should_stop = lambda: not state.is_active
            tstats = self.new_typing_stats()
            try:
                typed = await loop.run_in_executor(
                    None, lambda: self._type_message_sync(browser, message_text, humanizer, should_stop, tstats))
            except Exception as e:
                # Именно этот случай клиент видит как «набрало первые строки и остановилось»:
                # половина текста остаётся в поле. Пишем, на какой порции и почему оборвалось.
                kind = classify_driver_error(e)
                self.logger.error(
                    f"⌨ Набор оборван: {_typing_summary(tstats)}; {type(e).__name__}: {str(e)[:160]}", username)
                if kind == "closed":
                    return BROWSER_CLOSED
                try:
                    await loop.run_in_executor(
                        None, lambda: self._clear_composer_sync(browser, self._find_composer_sync(browser)))
                except Exception:
                    pass
                return RETRY
            if not typed:
                self.logger.warning(f"Набор прерван (аккаунт остановлен): {_typing_summary(tstats)}", username)
                return RETRY
            self.logger.info(f"⌨ Набрано: {_typing_summary(tstats)}", username)

            await asyncio.sleep(0.8)

            # 4. Проверяем, что в поле ровно наш текст; иначе — вставка одним куском
            probe = await self._probe_page(browser)
            expected = normalize_for_compare(message_text)
            actual = normalize_for_compare(probe.get("composerValue") if probe else "")
            if actual != expected:
                self.logger.warning(
                    f"Текст в поле отличается (ожидалось {len(expected)} симв., получено {len(actual)}). "
                    f"Повторяем вставкой целиком.", username)
                await loop.run_in_executor(None, lambda: self._insert_text_fallback_sync(browser, message_text))
                await asyncio.sleep(0.8)
                probe = await self._probe_page(browser)
                actual = normalize_for_compare(probe.get("composerValue") if probe else "")
                if actual != expected:
                    self.logger.error("Не удалось корректно заполнить поле ввода. Группа вернётся в очередь.", username)
                    try:
                        await loop.run_in_executor(
                            None, lambda: self._clear_composer_sync(browser, self._find_composer_sync(browser)))
                    except Exception:
                        pass
                    return RETRY

            # 5. Отправка
            sent, why = await self._send_message_button(browser, username, chat_id)
            if sent:
                self.logger.info(f"⏱ вся отправка заняла {time.monotonic() - t_start:.1f}с", username)
                await asyncio.sleep(random.uniform(2, 4))
                return SUCCESS
            if why == "limit":
                return LIMIT_REACHED
            return RETRY

        except Exception as e:
            if classify_driver_error(e) == "closed":
                return BROWSER_CLOSED
            self.logger.error(f"Ошибка при отправке сообщения в {group_url}: {type(e).__name__}: {str(e)[:200]}", username)
            return RETRY
