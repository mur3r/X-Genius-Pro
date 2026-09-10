"""
AccountManager: состояние аккаунтов, файлы accounts/groups, токены, экспорт.
"""

import asyncio
import gc
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from xgenius.accounts.auth import AuthMixin
from xgenius.accounts.health import HealthMixin
from xgenius.browser import BrowserManager
from xgenius.config import Config
from xgenius.core import FOLLOWERS_PROBE_JS
from xgenius.logger import Logger
from xgenius.models import AccountState, BrowserConfig


class AccountManager(HealthMixin, AuthMixin):

    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.accounts: Dict[str, AccountState] = {}
        self.browser_manager = BrowserManager(config, BrowserConfig())
        self.gui_instance = None  # Для связи с GUI

        # Временные сообщения для всех аккаунтов
        self.temp_messages_file = Path("temp_messages.json")
        self.temp_messages = self.load_temp_messages()
        # Ensure sent_this_cycle is set
        if "sent_this_cycle" not in self.temp_messages:
            self.temp_messages["sent_this_cycle"] = False

        # Статистика временных сообщений
        self.temp_messages_stats_file = Path("temp_messages_stats.json")
        self.temp_messages_stats = self.load_temp_messages_stats()

        # --- CACHE AND WORKER FOR GUI OPTIMIZATION ---
        self._cache_lock = threading.Lock()
        self.cached_data = []
        self.stop_worker = False
        threading.Thread(target=self._background_worker, daemon=True).start()
    

    def set_gui_instance(self, gui_instance):
        """Установка ссылки на GUI для доступа к Telegram боту"""
        self.gui_instance = gui_instance
    
    async def send_telegram_error(self, error_type: str, username: str = "", error_details: str = ""):
        """Отправка ошибки в Telegram"""
        try:
            if self.gui_instance and hasattr(self.gui_instance, 'telegram_bot_instance'):
                bot = self.gui_instance.telegram_bot_instance
                if bot and bot.running:
                    # Запускаем в отдельном потоке, чтобы не блокировать основной
                    asyncio.create_task(bot.send_error_alert(error_type, username, error_details))
        except Exception as e:
            print(f"Failed to send Telegram error: {e}")

    def _background_worker(self):
        """Background thread to prepare data for the GUI table."""
        counter = 0
        # Cache for file contents to reduce I/O
        cached_accounts = []
        cached_groups = {}
        accounts_file_mtime = 0
        groups_file_mtime = 0
        
        while not self.stop_worker:
            try:
                # Check if files changed before reading
                accounts_exists = self.config.accounts_file.exists()
                groups_exists = self.config.account_groups_file.exists()
                
                current_accounts_mtime = self.config.accounts_file.stat().st_mtime if accounts_exists else 0
                current_groups_mtime = self.config.account_groups_file.stat().st_mtime if groups_exists else 0
                
                # Only reload files if they've been modified
                if accounts_exists and current_accounts_mtime != accounts_file_mtime:
                    accounts_file_mtime = current_accounts_mtime
                    cached_accounts = self.load_accounts()
                elif not accounts_exists:
                    cached_accounts = []
                    
                if groups_exists and current_groups_mtime != groups_file_mtime:
                    groups_file_mtime = current_groups_mtime
                    try:
                        with open(self.config.account_groups_file, 'r', encoding='utf-8') as f:
                            cached_groups = json.load(f)
                    except Exception:
                        pass
                elif not groups_exists:
                    cached_groups = {}
                
                accounts_list = cached_accounts
                all_groups = cached_groups

                prepared_rows = []

                for idx, account in enumerate(accounts_list):
                    username = account["username"]
                    state = self.accounts.get(username)
                    
                    # --- НОВАЯ ЛОГИКА СТАТУСОВ (ИЕРАРХИЯ) ---
                    status_text = "Inactive"
                    status_color = "gray"
                    last_launch = "N/A"
                    groups_count = 0
                    
                    if state:
                        # Считаем группы
                        if state.groups:
                            groups_count = len(state.groups)
                        else:
                            groups_count = len(all_groups.get(username, []))

                        last_launch = state.last_action_time.strftime("%H:%M:%S")
                        
                        # 1. ПРИОРИТЕТ: ОШИБКИ И БЛОКИРОВКИ (включая перелогин)
                        if state.status_reason:
                            status_text = state.status_reason.upper() # Делаем капсом для важности
                            if "SUSPENDED" in status_text or "LOCKED" in status_text:
                                status_color = "#c0392b" # Темно-красный
                            elif "LIMIT" in status_text:
                                status_color = "#e74c3c" # Красный
                            elif "RELOGIN" in status_text:
                                status_text = "NEED RELOGIN" # Новый статус
                                status_color = "#9b59b6" # Фиолетовый
                            else:
                                status_color = "#d35400" # Оранжевый (Error)
                        
                        # 2. ПРИОРИТЕТ: ПАУЗА (Если нет ошибок, но нажата пауза)
                        elif state.is_paused:
                            status_text = "PAUSED"
                            status_color = "#f39c12" # Желто-оранжевый
                            
                        # 3. ПРИОРИТЕТ: ПАРСИНГ
                        elif state.is_parsing:
                            status_text = "PARSING"
                            status_color = "#9b59b6" # Фиолетовый
                            
                        # 4. ПРИОРИТЕТ: МЕЙЛИНГ (РАБОТА)
                        elif state.is_mailing:
                            status_text = "MAILING"
                            status_color = "#3498DB" # Голубой
                            
                        # 5. ПРИОРИТЕТ: АКТИВЕН (ПРОСТО ЗАЛОГИНЕН)
                        elif state.is_active:
                            status_text = "ACTIVE"
                            status_color = "#27ae60" # Зеленый
                    
                    else:
                        # Если state нет в памяти
                        groups_count = len(all_groups.get(username, []))

                    row_data = {
                        "index": idx,
                        "account": account,
                        "username": username,
                        "status_text": status_text,
                        "status_color": status_color,
                        "groups_count": groups_count,
                        "last_launch": last_launch
                    }
                    prepared_rows.append(row_data)

                with self._cache_lock:
                    self.cached_data = prepared_rows
                
                # --- OPTIMIZATION (GC COLLECT) ---
                # Reduced frequency: collect every 60 cycles (was 20) to reduce overhead
                counter += 1
                if counter > 60: 
                    gc.collect() 
                    counter = 0
                # ---------------------------------
                
                # Increased sleep to 3 seconds to reduce CPU usage (was 1.5)
                time.sleep(3) 
                
            except Exception as e:
                print(f"Background worker error: {e}")
                time.sleep(5)

    def get_table_data(self):
        """Thread-safe accessor for GUI."""
        with self._cache_lock:
            return list(self.cached_data)

    def save_groups(self):
        try:
            if self.config.account_groups_file.exists():
                with open(self.config.account_groups_file, 'r', encoding='utf-8') as f:
                    groups_data = json.load(f)
            else:
                groups_data = {}
            for username, state in self.accounts.items():
                if state.groups:
                    groups_data[username] = list(state.groups)
            with open(self.config.account_groups_file, 'w', encoding='utf-8') as f:
                json.dump(groups_data, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save groups: {e}")

    def load_saved_groups(self, username: str) -> Set[str]:
        try:
            if self.config.account_groups_file.exists():
                with open(self.config.account_groups_file, 'r', encoding='utf-8') as f:
                    groups_data = json.load(f)
                    return set(groups_data.get(username, []))
        except Exception as e:
            self.logger.error(f"Failed to load groups for {username}: {e}")
        return set()

    def load_accounts(self) -> List[dict]:
        try:
            if self.config.accounts_file.exists():
                with open(self.config.accounts_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("accounts", [])
            return []
        except Exception as e:
            self.logger.error(f"Failed to load accounts: {e}")
            return []

    def save_accounts(self, accounts: List[dict]) -> None:
        try:
            with open(self.config.accounts_file, 'w', encoding='utf-8') as f:
                json.dump({"accounts": accounts}, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save accounts: {e}")

    async def get_auth_tokens(self, browser: webdriver.Chrome) -> tuple[Optional[str], Optional[str]]:
        """Получение токенов авторизации из браузера"""
        try:
            loop = asyncio.get_event_loop()
            # Получаем все cookies
            cookies = await loop.run_in_executor(None, lambda: browser.get_cookies())
            
            auth_token = None
            ct0_token = None
            
            # Ищем нужные куки
            for cookie in cookies:
                if cookie.get('name') == 'auth_token':
                    auth_token = cookie.get('value')
                elif cookie.get('name') == 'ct0':
                    ct0_token = cookie.get('value')
            
            # Если не нашли в куках, пробуем получить из localStorage через JavaScript
            if not auth_token or not ct0_token:
                try:
                    tokens = await loop.run_in_executor(None, lambda: browser.execute_script(
                        """
                        try {
                            return {
                                'auth_token': localStorage.getItem('auth_token'),
                                'ct0': localStorage.getItem('ct0')
                            };
                        } catch(e) {
                            return null;
                        }
                        """
                    ))
                    
                    if tokens and isinstance(tokens, dict):
                        if not auth_token and tokens.get('auth_token'):
                            auth_token = tokens['auth_token']
                        if not ct0_token and tokens.get('ct0'):
                            ct0_token = tokens['ct0']
                except Exception:
                    pass
            
            self.logger.info(f"Получены токены: auth_token={'SET' if auth_token else 'N/A'}, ct0={'SET' if ct0_token else 'N/A'}")
            return auth_token, ct0_token
            
        except Exception as e:
            self.logger.error(f"Ошибка получения токенов: {e}")
            return None, None

    async def get_followers_count(self, browser: webdriver.Chrome, username: str) -> int:
        """
        Количество подписчиков одним JS-вызовом.
        Старая версия: xpath-перебор, regex по page_source (мегабайты) и обход 300
        элементов с outerHTML на каждом — сотни HTTP-запросов к chromedriver при каждом
        логине/перелогине.
        """
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: browser.get(f"https://x.com/{username}"))

            def _wait_anchor():
                WebDriverWait(browser, 12).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//a[contains(@href, '/verified_followers') or contains(@href, '/followers')]"))
                )
                return browser.execute_script(FOLLOWERS_PROBE_JS)

            text = await loop.run_in_executor(None, _wait_anchor)
            followers_count = self._parse_count(text or "")
            self.logger.info(f"Количество подписчиков @{username}: {followers_count}", username)
            return followers_count
        except Exception as e:
            self.logger.warning(f"Не удалось получить подписчиков: {type(e).__name__}", username)
            return 0

    def _parse_count(self, text: str) -> int:
        """'1,234 Followers' / '12.5K' / '1.2M' / '1 234 подписчиков' / '12,5 тыс.' -> int.
        Старый вариант ловил кириллическую 'к' внутри слова 'подписчиков' и умножал на 1000."""
        if not text:
            return 0
        m = re.search(r"(\d[\d\s .,]*)\s*(K|M|k|m|К|М|тыс|млн)?", text.strip())
        if not m:
            return 0
        num = m.group(1).replace(" ", "").replace(" ", "")
        suffix = (m.group(2) or "").lower()
        mult = 1
        if suffix in ("k", "к", "тыс"):
            mult = 1000
        elif suffix in ("m", "м", "млн"):
            mult = 1_000_000
        if mult == 1:
            num = num.replace(",", "").replace(".", "")
        else:
            num = num.replace(",", ".")
            if num.count(".") > 1:
                num = num.replace(".", "")
        try:
            return int(float(num) * mult)
        except ValueError:
            return 0

    def export_groups_to_file(self, usernames: List[str]) -> str:
        """
        Экспортирует информацию о чатах выбранных аккаунтов в текстовый файл.
        Возвращает путь к созданному файлу.
        """
        try:
            # Создаем имя файла с временной меткой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_filename = f"groups_export_{timestamp}.txt"
            export_path = self.config.base_dir / export_filename
            
            total_groups = 0
            accounts_info = []
            
            for username in usernames:
                # Загружаем группы для аккаунта
                if username in self.accounts:
                    groups = self.accounts[username].groups
                else:
                    # Пытаемся загрузить из сохраненных
                    groups = self.load_saved_groups(username)
                
                if groups:
                    groups_list = list(groups)
                    total_groups += len(groups_list)
                    accounts_info.append({
                        "username": username,
                        "count": len(groups_list),
                        "groups": groups_list
                    })
                else:
                    accounts_info.append({
                        "username": username,
                        "count": 0,
                        "groups": []
                    })
            
            # Формируем содержимое файла
            content_lines = []
            content_lines.append("=" * 60)
            content_lines.append(f"ЭКСПОРТ ЧАТОВ - {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
            content_lines.append(f"Общее количество аккаунтов: {len(usernames)}")
            content_lines.append(f"Общее количество чатов: {total_groups}")
            content_lines.append("=" * 60)
            content_lines.append("")
            
            for i, acc_info in enumerate(accounts_info, 1):
                content_lines.append(f"{i}. Аккаунт @{acc_info['username']} - {acc_info['count']} чатов")
                content_lines.append("-" * 40)
                
                if acc_info['groups']:
                    for j, group_link in enumerate(acc_info['groups'], 1):
                        content_lines.append(f"   {j}. {group_link}")
                else:
                    content_lines.append("   Нет сохраненных чатов")
                
                content_lines.append("")  # Пустая строка между аккаунтами
            
            content_lines.append("=" * 60)
            content_lines.append("ЭКСПОРТ ЗАВЕРШЕН")
            content_lines.append("=" * 60)
            
            # Записываем в файл
            with open(export_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content_lines))
            
            self.logger.info(f"Экспортирована информация о чатах для {len(usernames)} аккаунтов в {export_path}")
            return str(export_path)
            
        except Exception as e:
            self.logger.error(f"Ошибка экспорта чатов: {e}")
            raise Exception(f"Не удалось экспортировать чаты: {e}")

    def load_temp_messages(self) -> Dict[str, Any]:
        """Загружает временные сообщения из файла."""
        try:
            if self.temp_messages_file.exists():
                with open(self.temp_messages_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Ошибка загрузки временных сообщений: {e}")
        return {}

    def save_temp_messages(self):
        """Сохраняет временные сообщения в файл."""
        try:
            with open(self.temp_messages_file, 'w', encoding='utf-8') as f:
                json.dump(self.temp_messages, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Ошибка сохранения временных сообщений: {e}")

    def load_temp_messages_stats(self) -> Dict[str, Any]:
        """Загружает статистику временных сообщений из файла."""
        try:
            if self.temp_messages_stats_file.exists():
                with open(self.temp_messages_stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Ошибка загрузки статистики временных сообщений: {e}")
        return {}

    def save_temp_messages_stats(self):
        """Сохраняет статистику временных сообщений в файл."""
        try:
            with open(self.temp_messages_stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.temp_messages_stats, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Ошибка сохранения статистики временных сообщений: {e}")
