"""
Комментарии и ретвиты (часть TwitterOperations).
"""

import asyncio
import os
import random
from datetime import datetime

import pyperclip
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from xgenius.text_utils import parse_followers_count
from xgenius.twitter.common import new_get_followers_count


class SocialMixin:
    """Методы TwitterOperations: post_comment_with_photo, retweet_pinned_post, perform_retweets."""

    async def post_comment_with_photo(self, browser, target_username: str, text: str, photo_path: str, our_username: str, account_manager) -> bool:
        try:
            loop = asyncio.get_event_loop()
            target_username = target_username.strip()
            target_username = target_username.replace("https://x.com/", "") \
                                             .replace("https://twitter.com/", "") \
                                             .replace("http://x.com/", "") \
                                             .replace("http://twitter.com/", "") \
                                             .replace("www.", "") \
                                             .replace("@", "") \
                                             .strip("/")

            self.logger.info(f"Пытаемся оставить умный комментарий @{target_username}...", our_username)
            
            await loop.run_in_executor(None, lambda: browser.get(f"https://x.com/{target_username}"))
            
            wait_time = random.uniform(15, 30)
            self.logger.info(f"Ждем {wait_time:.1f}с после посещения профиля...", our_username)
            await asyncio.sleep(wait_time)

            if not await account_manager.check_account_health(our_username):
                return False

            try:
                await loop.run_in_executor(None, lambda: WebDriverWait(browser, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "article"))
                ))
            except Exception:
                self.logger.warning("Твиты не загрузились.", our_username)
                return False
            
            try:
                pinned = await loop.run_in_executor(None, lambda: browser.execute_script(
                    "var elems = document.querySelectorAll('div[data-testid=\"socialContext\"]');"
                    "return Array.from(elems).find(el => el.innerText.includes('Pinned'));"
                ))
                
                if pinned:
                     tweet_base = await loop.run_in_executor(None, lambda: pinned.find_element(By.XPATH, "./ancestor::article"))
                else:
                     tweet_base = await loop.run_in_executor(None, lambda: browser.find_element(By.TAG_NAME, "article"))
                
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", tweet_base))
                
                wait_time = random.uniform(15, 30)
                self.logger.info(f"Найден твит. Ждем {wait_time:.1f}с...", our_username)
                await asyncio.sleep(wait_time)

            except Exception:
                self.logger.warning("Не удалось идентифицировать валидный элемент твита.", our_username)
                return False
            
            try:
                reply_btn = await loop.run_in_executor(None, lambda: WebDriverWait(tweet_base, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='reply']"))
                ))
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", reply_btn))
            except Exception:
                 self.logger.warning("Кнопка ответа не найдена.", our_username)
                 return False

            await asyncio.sleep(1) 

            if photo_path and os.path.exists(photo_path):
                try:
                    self.logger.info("Загружаем фото...", our_username)
                    file_input = await loop.run_in_executor(None, lambda: browser.find_element(By.XPATH, "//input[@type='file']"))
                    await loop.run_in_executor(None, lambda: file_input.send_keys(os.path.abspath(photo_path)))
                    
                    wait_time = random.uniform(15, 30)
                    self.logger.info(f"Фото загружено. Ждем {wait_time:.1f}с...", our_username)
                    await asyncio.sleep(wait_time)
                    
                except Exception as e:
                    self.logger.error(f"Ошибка загрузки фото: {e}", our_username)

            try:
                text_box = await loop.run_in_executor(None, lambda: WebDriverWait(browser, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox'][aria-label='Post text']"))
                ))
                await asyncio.sleep(2)
                await loop.run_in_executor(None, lambda: text_box.click())
                
                pyperclip.copy(text)
                await loop.run_in_executor(None, lambda: text_box.send_keys(Keys.CONTROL, 'v'))
                
                wait_time = random.uniform(15, 30)
                self.logger.info(f"Текст вставлен. Ждем {wait_time:.1f}с перед отправкой...", our_username)
                await asyncio.sleep(wait_time)
                
            except Exception:
                self.logger.warning("Не удалось найти текстовое поле для ответа.", our_username)
                return False

            try:
                post_btn = await loop.run_in_executor(None, lambda: browser.find_element(By.CSS_SELECTOR, "[data-testid='tweetButton']"))
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", post_btn))
                
                self.logger.info("Умный комментарий отправлен!", our_username)
                self.stats_manager.record_comment(our_username)
                
                # --- ФУНКЦИЯ 3: СОХРАНЕНИЕ УСПЕШНЫХ КОММЕНТАРИЕВ В ОТДЕЛЬНЫЙ ФАЙЛ ---
                try:
                    log_path = self.logger.config.logs_dir / "comments_success.txt"
                    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"[{timestamp}] @{our_username} оставил коммент юзеру @{target_username}\n")
                except Exception as e:
                    print(f"Ошибка записи лога комментариев: {e}")
                
                await asyncio.sleep(3) 
                return True
            except Exception:
                self.logger.error("Не удалось найти кнопку Отправить.", our_username)
                return False

        except Exception as e:
            err_str = str(e)
            if "WinError 10061" in err_str or "HTTPConnectionPool" in err_str:
                self.logger.warning("Потеряно соединение с браузером во время комментирования.", our_username)
                return False

            self.logger.error(f"Ошибка умного комментария: {err_str}", our_username)
            await account_manager.handle_lock_if_any(our_username)
            return False

    async def retweet_pinned_post(self, browser, target_username: str, our_username: str) -> tuple[str, str]:
        """
        Возвращает кортеж: (статус, текст_подписчиков)
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: browser.get(f"https://x.com/{target_username}"))
            await asyncio.sleep(3)
            
            followers_text = await new_get_followers_count(browser, target_username)
            
            if parse_followers_count(followers_text) < 2000:
                self.logger.info("Пропускаем ретвит: недостаточно подписчиков", our_username)
                return "Skipping retweet", followers_text
            
            pinned = None
            for _ in range(3):
                try:
                    pinned = await loop.run_in_executor(None, lambda: browser.execute_script(
                        "var elems = document.querySelectorAll('div[data-testid=\"socialContext\"]');"
                        "return Array.from(elems).find(el => el.innerText.includes('Pinned'));"
                    ))
                    if pinned:
                        break
                except Exception:
                    await asyncio.sleep(2)
            
            if not pinned:
                self.logger.info("Пропускаем ретвит: закрепленный пост не найден", our_username)
                return "Skipping retweet", followers_text
            
            await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView(true);", pinned))
            await asyncio.sleep(2)
            
            retweet_btn = None
            for _ in range(3):
                try:
                    retweet_btn = await loop.run_in_executor(None, lambda: browser.execute_script(
                        "return document.querySelector('[data-testid=\"retweet\"]');"
                    ))
                    if retweet_btn:
                        break
                except Exception:
                    await asyncio.sleep(2)
            
            if not retweet_btn:
                self.logger.info("Пропускаем ретвит: кнопка ретвита не найдена", our_username)
                return "Skipping retweet", followers_text
            
            await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView(true);", retweet_btn))
            await asyncio.sleep(2)
            await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", retweet_btn))
            await asyncio.sleep(2)
            
            confirm_btn = None
            for _ in range(3):
                try:
                    confirm_btn = await loop.run_in_executor(None, lambda: browser.execute_script(
                        "return document.querySelector('[data-testid=\"retweetConfirm\"]');"
                    ))
                    if confirm_btn:
                        break
                except Exception:
                    await asyncio.sleep(2)
            
            if confirm_btn:
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].scrollIntoView(true);", confirm_btn))
                await asyncio.sleep(2)
                await loop.run_in_executor(None, lambda: browser.execute_script("arguments[0].click();", confirm_btn))
                await asyncio.sleep(2)
                self.logger.info("Ретвит подтвержден", our_username)
                
                # --- УСПЕХ, ВОЗВРАЩАЕМ ПОДПИСЧИКОВ ---
                return "Retweet completed", followers_text
            
            return "Skipping retweet", followers_text
            
        except Exception as e:
            self.logger.error(f"Ошибка ретвита: {str(e)}", our_username)
            return "Skipping retweet", "0"

    # --- ИЗМЕНЕННЫЙ МЕТОД: УЧЕТ ЛИМИТА ЗА 24 ЧАСА + ЗАПИСЬ ПОДПИСЧИКОВ ---
    async def perform_retweets(self, browser, account_state, our_username: str, account_manager) -> None:
        try:
            # Настройка: сколько делать ретвитов за ОДИН проход (цикл)
            per_cycle_limit = account_state.cycle_settings.retweet_count
            
            # Настройка: ГЛОБАЛЬНЫЙ лимит за 24 часа
            daily_limit = account_state.cycle_settings.max_total_retweets
            
            if per_cycle_limit <= 0:
                self.logger.info("Лимит ретвитов за цикл равен 0, пропускаем.", our_username)
                return

            # Получаем текущее кол-во ретвитов за 24 часа из базы
            current_24h_count = self.stats_manager.get_retweets_24h_count(our_username)
            
            self.logger.info(f"Статистика ретвитов за 24ч: {current_24h_count}/{daily_limit}", our_username)

            if current_24h_count >= daily_limit:
                self.logger.info(f"Дневной лимит ретвитов достигнут ({current_24h_count} >= {daily_limit}). Пропускаем.", our_username)
                return

            # Вычисляем, сколько можем сделать сейчас
            remaining_today = daily_limit - current_24h_count
            to_do_now = min(per_cycle_limit, remaining_today)
            
            if to_do_now <= 0:
                return

            targets = await self.get_target_sender_usernames(browser, count=to_do_now, used_targets=account_state.used_targets)
            self.logger.info(f"Найдены цели для ретвита: {targets}", our_username)
            
            if not targets:
                return
                
            for target in targets:
                # Повторная проверка перед каждым действием
                if self.stats_manager.get_retweets_24h_count(our_username) >= daily_limit:
                    self.logger.info("Дневной лимит достигнут во время цикла. Останавливаем ретвиты.", our_username)
                    break
                
                # --- ТЕПЕРЬ ПОЛУЧАЕМ И СТАТУС, И ПОДПИСЧИКОВ ---
                result, followers_count = await self.retweet_pinned_post(browser, target, our_username)
                self.logger.info(f"Результат ретвита для {target} ({followers_count} подписчиков): {result}", our_username)
                
                if result == "Retweet completed":
                    # Локальный счетчик
                    account_state.retweets_count += 1 
                    self.stats_manager.record_retweet(our_username)
                    
                    # --- СОХРАНЕНИЕ УСПЕШНЫХ РЕТВИТОВ В ФАЙЛ (С ПОДПИСЧИКАМИ) ---
                    try:
                        log_path = self.logger.config.logs_dir / "retweets_success.txt"
                        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                        with open(log_path, "a", encoding="utf-8") as f:
                            # Добавлена информация о подписчиках
                            f.write(f"[{timestamp}] @{our_username} сделал ретвит юзера @{target} (Followers: {followers_count})\n")
                    except Exception as e:
                        print(f"Ошибка записи лога ретвитов: {e}")
                    # ----------------------------------------------------------------
                    
                    await asyncio.sleep(random.uniform(40, 80))

        except Exception as e:
            self.logger.error(f"Ошибка выполнения ретвитов: {str(e)}", our_username)
