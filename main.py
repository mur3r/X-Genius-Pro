import os, sys, asyncio, json, logging, random, threading, tkinter as tk, zipfile, time, re, sqlite3
import html
import subprocess
import shutil  # Для безопасного сохранения файлов
import gc  # Для принудительной очистки памяти
import urllib3
import warnings
import selenium.webdriver
import selenium.webdriver.chrome.webdriver
import selenium_stealth
from enum import Enum
# Подавляем предупреждения о устаревшем get_event_loop
warnings.filterwarnings('ignore', category=DeprecationWarning, module='asyncio')
# Подавляем ВСЕ предупреждения urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.HTTPWarning)
# Подавляем логи urllib3
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

# Безопасный режим проверки: True = набирает сообщение, но НЕ отправляет его.
# После успешной проверки можно вручную переключить на False.
DRY_RUN_MAILING = False
# Increase connection pool size for better performance with many accounts
urllib3.PoolManager(maxsize=180)
# Также увеличим пул для requests
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Создаем сессию с большим пулом
session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1)
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=180, max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, List, Set, Dict, Any

from selenium.common.exceptions import TimeoutException
import csv
from io import StringIO
import customtkinter as ctk
from tkinter import messagebox
import tkinter.filedialog as fd
import pyperclip

# Инициализация Tkinter для получения размеров экрана
try:
    _root = tk.Tk()
    _root.withdraw()
    SCREEN_WIDTH = _root.winfo_screenwidth()
    SCREEN_HEIGHT = _root.winfo_screenheight()
    _root.destroy()
except:
    SCREEN_WIDTH = 1920
    SCREEN_HEIGHT = 1080

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth

# Предполагается наличие файла human1.py в той же папке
from human1 import Humanizer

# Для Telegram бота
import socket
import uuid
import hashlib
import platform
import psutil
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters,
    ContextTypes
)
@dataclass
class SystemInfo:
    computer_name: str
    ip_address: str
    mac_address: str
    os_name: str
    os_version: str
    python_version: str
    program_path: str
    cpu_count: int
    total_memory: float
    disk_usage: Dict[str, Any]
    
# --------------------- Telegram Bot Configuration ---------------------
TELEGRAM_BOT_TOKEN = "8322898928:AAFfmn4fQOeJKt_ShbDMbFGnPc0F3PZB8i0"
TELEGRAM_CHAT_ID = "441164219"

# Google Sheets Configuration (спец-сообщения)
GOOGLE_SPEC_SHEET_URL = "https://docs.google.com/spreadsheets/d/1ugbPnYT_kFrqglr7wf_ZzvITL5hLgTIN8KjHgEYqM8k/export?format=csv"
USE_GOOGLE_SPEC = True  # Читать спец-сообщения из Google Таблицы

CLIPBOARD_LOCK = threading.Lock()

@dataclass
class BotConfig:
    token: str = TELEGRAM_BOT_TOKEN
    chat_id: str = TELEGRAM_CHAT_ID
    enable_auto_reports: bool = True
    report_interval: int = 3600
    enable_error_alerts: bool = True
    enable_startup_notification: bool = True
    instance_id: str = None
    pc_id: str = None

    def __post_init__(self):
        if not self.instance_id:
            self.instance_id = f"TG_{hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()[:8].upper()}"
        if not self.pc_id:
            # Use computer name for more stable PC ID
            import socket
            computer_name = socket.gethostname()
            self.pc_id = f"PC_{hashlib.md5(computer_name.encode()).hexdigest()[:6].upper()}"

class AuthStatus(Enum):
    OK = "OK"
    PAGE_DOWN = "PAGE_DOWN"
    NEED_RELOGIN = "NEED_RELOGIN"
    LOCKED = "LOCKED"

class DatabaseManager:
    def __init__(self, db_path="monitoring_bot.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        with self.conn:
            self.conn.execute('''CREATE TABLE IF NOT EXISTS pcs (
                pc_id TEXT PRIMARY KEY,
                computer_name TEXT,
                ip_address TEXT,
                os_name TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS accounts (
                pc_id TEXT,
                username TEXT,
                password TEXT,
                proxy TEXT,
                user_agent TEXT,
                group_name TEXT,
                is_active INTEGER,
                is_mailing INTEGER,
                is_paused INTEGER,
                need_relogin INTEGER,
                status_reason TEXT,
                messages_sent INTEGER,
                retweets_count INTEGER,
                auth_token TEXT,
                ct0_token TEXT,
                groups_count INTEGER,
                followers_count INTEGER DEFAULT 0,
                last_action TEXT,
                cookies TEXT,
                PRIMARY KEY (pc_id, username)
            )''')
            # Добавляем колонку followers_count если ее нет
            try:
                self.conn.execute('ALTER TABLE accounts ADD COLUMN followers_count INTEGER DEFAULT 0')
            except:
                pass  # Колонка уже существует
            
            # Таблица для временных сообщений (спец сообщений)
            self.conn.execute('''CREATE TABLE IF NOT EXISTS temp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                messages TEXT,
                message_interval INTEGER DEFAULT 0,
                messages_sent_count INTEGER DEFAULT 0,
                sent_this_interval INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            # Миграция: добавляем колонку message_interval если её нет
            try:
                self.conn.execute('ALTER TABLE temp_messages ADD COLUMN message_interval INTEGER DEFAULT 0')
            except:
                pass  # Колонка уже существует
            
            # Миграция: добавляем колонку messages_sent_count если её нет
            try:
                self.conn.execute('ALTER TABLE temp_messages ADD COLUMN messages_sent_count INTEGER DEFAULT 0')
            except:
                pass  # Колонка уже существует
            
            # Миграция: добавляем колонку sent_this_interval если её нет
            try:
                self.conn.execute('ALTER TABLE temp_messages ADD COLUMN sent_this_interval INTEGER DEFAULT 0')
            except:
                pass  # Колонка уже существует

    def sync_pc_info(self, pc_id, system_info):
        with self.conn:
            self.conn.execute('''INSERT OR REPLACE INTO pcs (pc_id, computer_name, ip_address, os_name, last_seen)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (pc_id, system_info.computer_name, system_info.ip_address, system_info.os_name))

    def sync_accounts(self, pc_id, accounts_data):
        with self.conn:
            self.conn.executemany('''INSERT OR REPLACE INTO accounts (
                pc_id, username, password, proxy, user_agent, group_name, is_active, is_mailing, is_paused,
                need_relogin, status_reason, messages_sent, retweets_count, auth_token, ct0_token,
                groups_count, last_action, cookies
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [(pc_id, acc['username'], acc['password'], acc['proxy'], acc['user_agent'], acc['group'],
              acc['is_active'], acc['is_mailing'], acc['is_paused'], acc['need_relogin'], acc['status_reason'],
              acc['messages_sent'], acc['retweets_count'], acc['auth_token'], acc['ct0_token'],
              acc['groups_count'], acc['last_action'], acc.get('cookies', '{}')) for acc in accounts_data])

    def get_pcs(self):
        with self.conn:
            cursor = self.conn.execute('SELECT pc_id, computer_name, ip_address, os_name, last_seen FROM pcs ORDER BY last_seen DESC')
            return cursor.fetchall()

    def get_accounts_for_pc(self, pc_id):
        with self.conn:
            cursor = self.conn.execute('SELECT * FROM accounts WHERE pc_id = ?', (pc_id,))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def update_cookies(self, pc_id, username, cookies):
        cookies_json = json.dumps(cookies)
        with self.conn:
            self.conn.execute('UPDATE accounts SET cookies = ? WHERE pc_id = ? AND username = ?', (cookies_json, pc_id, username))

    def update_tokens(self, pc_id, username, auth_token, ct0_token):
        with self.conn:
            self.conn.execute('UPDATE accounts SET auth_token = ?, ct0_token = ? WHERE pc_id = ? AND username = ?', (auth_token, ct0_token, pc_id, username))
    
    def update_followers_count(self, pc_id, username, followers_count):
        """Обновляет количество подписчиков"""
        with self.conn:
            self.conn.execute('UPDATE accounts SET followers_count = ? WHERE pc_id = ? AND username = ?', (followers_count, pc_id, username))

    def get_cookies(self, pc_id, username):
        with self.conn:
            cursor = self.conn.execute('SELECT cookies FROM accounts WHERE pc_id = ? AND username = ?', (pc_id, username))
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return {}

    def delete_pc(self, pc_id):
        """Удаляет ПК и все связанные аккаунты из БД"""
        with self.conn:
            self.conn.execute('DELETE FROM accounts WHERE pc_id = ?', (pc_id,))
            self.conn.execute('DELETE FROM pcs WHERE pc_id = ?', (pc_id,))

    def delete_all_pcs(self):
        """Удаляет все ПК и аккаунты из БД"""
        with self.conn:
            self.conn.execute('DELETE FROM accounts')
            self.conn.execute('DELETE FROM pcs')

    def delete_old_pcs(self, days: int = 7):
        """Удаляет ПК, которые не были активны больше указанного количества дней"""
        with self.conn:
            # Получаем старые ПК
            cursor = self.conn.execute(
                "SELECT pc_id FROM pcs WHERE last_seen < datetime('now', ?)",
                (f'-{days} days',)
            )
            old_pcs = [row[0] for row in cursor.fetchall()]
            
            # Удаляем аккаунты и ПК
            for pc_id in old_pcs:
                self.conn.execute('DELETE FROM accounts WHERE pc_id = ?', (pc_id,))
                self.conn.execute('DELETE FROM pcs WHERE pc_id = ?', (pc_id,))
            
            return len(old_pcs)
    
    def get_all_tokens_across_pcs(self) -> Dict[str, List[Dict]]:
        """Получает все токены от всех ПК для централизованного хранения"""
        with self.conn:
            cursor = self.conn.execute('SELECT pc_id, username, auth_token, ct0_token FROM accounts WHERE auth_token != "N/A" OR ct0_token != "N/A"')
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                pc_id, username, auth_token, ct0_token = row
                if pc_id not in result:
                    result[pc_id] = []
                result[pc_id].append({
                    'username': username,
                    'auth_token': auth_token,
                    'ct0_token': ct0_token
                })
            return result
    
    def get_pc_count(self) -> int:
        """Возвращает количество активных ПК"""
        with self.conn:
            cursor = self.conn.execute('SELECT COUNT(*) FROM pcs')
            return cursor.fetchone()[0]
    
    def get_total_accounts_count(self) -> int:
        """Возвращает общее количество аккаунтов от всех ПК"""
        with self.conn:
            cursor = self.conn.execute('SELECT COUNT(*) FROM accounts')
            return cursor.fetchone()[0]
    
    def get_all_accounts_stats(self, pc_id: Optional[str] = None) -> Dict[str, Any]:
        """Возвращает статистику по всем аккаунтам от всех ПК или одному указанному ПК"""
        with self.conn:
            stats = {
                'total_accounts': 0,
                'active_accounts': 0,
                'mailing_accounts': 0,
                'paused_accounts': 0,
                'blocked_accounts': 0,
                'total_messages': 0,
                'total_retweets': 0,
                'pcs_count': 0,
                'accounts_by_pc': {}
            }
            
            # Общая статистика
            if pc_id:
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE pc_id = ?', (pc_id,))
                stats['total_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE pc_id = ? AND is_active = 1', (pc_id,))
                stats['active_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE pc_id = ? AND is_mailing = 1', (pc_id,))
                stats['mailing_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE pc_id = ? AND is_paused = 1', (pc_id,))
                stats['paused_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute("SELECT COUNT(*) FROM accounts WHERE pc_id = ? AND status_reason = 'SUSPENDED'", (pc_id,))
                stats['blocked_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT SUM(messages_sent) FROM accounts WHERE pc_id = ?', (pc_id,))
                stats['total_messages'] = cursor.fetchone()[0] or 0
                
                cursor = self.conn.execute('SELECT SUM(retweets_count) FROM accounts WHERE pc_id = ?', (pc_id,))
                stats['total_retweets'] = cursor.fetchone()[0] or 0
                
                stats['pcs_count'] = 1
                
                # Статистика по одному ПК
                stats['accounts_by_pc'][pc_id] = {
                    'accounts_count': stats['total_accounts'],
                    'messages': stats['total_messages'],
                    'retweets': stats['total_retweets']
                }
            else:
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts')
                stats['total_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE is_active = 1')
                stats['active_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE is_mailing = 1')
                stats['mailing_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM accounts WHERE is_paused = 1')
                stats['paused_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute("SELECT COUNT(*) FROM accounts WHERE status_reason = 'SUSPENDED'")
                stats['blocked_accounts'] = cursor.fetchone()[0]
                
                cursor = self.conn.execute('SELECT SUM(messages_sent) FROM accounts')
                stats['total_messages'] = cursor.fetchone()[0] or 0
                
                cursor = self.conn.execute('SELECT SUM(retweets_count) FROM accounts')
                stats['total_retweets'] = cursor.fetchone()[0] or 0
                
                cursor = self.conn.execute('SELECT COUNT(*) FROM pcs')
                stats['pcs_count'] = cursor.fetchone()[0]
                
                # Статистика по ПК
                cursor = self.conn.execute('SELECT pc_id, COUNT(*), SUM(messages_sent), SUM(retweets_count) FROM accounts GROUP BY pc_id')
                for row in cursor.fetchall():
                    stats['accounts_by_pc'][row[0]] = {
                        'accounts_count': row[1],
                        'messages': row[2] or 0,
                        'retweets': row[3] or 0
                    }
            
            return stats
    
    # --- Методы для временных сообщений (спец сообщений) ---
    def save_temp_messages(self, messages: list, message_interval: int, messages_sent_count: int = 0):
        """Сохраняет временные сообщения в БД (интервальная логика)"""
        messages_json = json.dumps(messages, ensure_ascii=False)
        with self.conn:
            # Удаляем старые записи и вставляем новую
            self.conn.execute('DELETE FROM temp_messages')
            self.conn.execute(
                "INSERT INTO temp_messages (messages, message_interval, messages_sent_count, sent_this_interval, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (messages_json, message_interval, messages_sent_count, 0)
            )
    
    def load_temp_messages(self) -> dict:
        """Загружает временные сообщения из БД"""
        with self.conn:
            cursor = self.conn.execute('SELECT messages, message_interval, messages_sent_count, sent_this_interval FROM temp_messages ORDER BY updated_at DESC LIMIT 1')
            row = cursor.fetchone()
            if row:
                return {
                    "messages": json.loads(row[0]),
                    "message_interval": row[1] if row[1] else 0,
                    "messages_sent_count": row[2] if row[2] else 0,
                    "sent_this_interval": bool(row[3]) if row[3] is not None else False
                }
            return {"messages": [], "message_interval": 0, "messages_sent_count": 0, "sent_this_interval": False}
    
    def update_temp_messages_sent_interval(self, sent: bool):
        """Обновляет флаг sent_this_interval"""
        with self.conn:
            self.conn.execute('UPDATE temp_messages SET sent_this_interval = ?, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT id FROM temp_messages ORDER BY updated_at DESC LIMIT 1)', (1 if sent else 0,))
    
    def increment_temp_messages_count(self):
        """Увеличивает счетчик отправленных сообщений на 1"""
        with self.conn:
            self.conn.execute('UPDATE temp_messages SET messages_sent_count = messages_sent_count + 1, updated_at = CURRENT_TIMESTAMP')
    
    def clear_temp_messages(self):
        """Очищает временные сообщения"""
        with self.conn:
            self.conn.execute('DELETE FROM temp_messages')
class TextUniqizer:
    """Уникализация текста путем замены похожих символов и добавления смайлов"""
    
    CYRILLIC_TO_LATIN = {
        'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y', 'х': 'x',
        'А': 'A', 'Е': 'E', 'О': 'O', 'Р': 'P', 'С': 'C', 'Х': 'X'
    }
    
    EMOJIS = ["🔥", "⚡", "✨", "🚀", "💥", "🎯", "💎", "⭐", "🌐", "📌", "✅", "💬", "🎁"]

    @classmethod
    def uniqueize(cls, text: str) -> str:
        res = []
        for char in text:
            # 30% chance to replace cyrillic character with visually identical latin
            if char in cls.CYRILLIC_TO_LATIN and random.random() < 0.3:
                res.append(cls.CYRILLIC_TO_LATIN[char])
            else:
                res.append(char)
        
        result_text = "".join(res)
        
        # Add random emoji at the end or inside
        if random.random() < 0.7:
            result_text += f" {random.choice(cls.EMOJIS)}"
            
        return result_text


# =====================================================================
# 🔄 ОСНОВНОЙ МОДУЛЬ: ЦИКЛ РАССЫЛКИ И СМАРТ-КОММЕНТИНГ
# =====================================================================

def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы Markdown для Telegram."""
    if not text:
        return text
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def log_account_to_file(username: str, password: str, proxy: str, auth_token: str, ct0_token: str, groups_count: int, followers_count: int):
    """
    Записывает данные аккаунта в файл logstest в формате:
    логин:пасс:прокси:аутх_токен:цто:колво_чатов:колво_подписчиков
    """
    try:
        import os
        log_file = os.path.join(os.getcwd(), 'logstest')
        log_line = f"{username}:{password}:{proxy}:{auth_token}:{ct0_token}:{groups_count}:{followers_count}\n"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)
        print(f"[LOGSTEST] Записаны данные аккаунта {username} в файл {log_file}")
    except Exception as e:
        print(f"[LOGSTEST] Ошибка записи в файл: {e}")


def escape_html(text: str) -> str:
    """Безопасно экранирует HTML-символы для Telegram."""
    if not text:
        return ""
    # Экранируем все HTML-символы
    escaped = html.escape(str(text))
    return escaped


def format_html_message(text: str, bold: bool = False, pre: bool = False) -> str:
    """
    Форматирует текст для HTML-режима Telegram.
    Все динамические данные должны быть экранированы через escape_html().
    """
    text = str(text)
    if pre:
        return f"<pre>{text}</pre>"
    elif bold:
        return f"<b>{text}</b>"
    else:
        return text


async def safe_send_message(bot, chat_id: str, text: str, **kwargs) -> bool:
    """
    Безопасно отправляет сообщение с HTML форматированием.
    Все динамические данные должны быть предварительно экранированы через escape_html().
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", **kwargs)
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Если ошибка связана с парсингом HTML, пробуем без форматирования
        if "can't parse entities" in error_str or "parse" in error_str:
            try:
                # Пробуем отправить как plain text (без parse_mode)
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=None, **kwargs)
                return True
            except Exception as e2:
                print(f"Error sending message without formatting: {e2}")
                return False
        else:
            print(f"Error sending message: {e}")
            return False


async def safe_reply_text(message, text: str, **kwargs) -> bool:
    """
    Безопасно отвечает на сообщение с HTML форматированием.
    Все динамические данные должны быть предварительно экранированы через escape_html().
    """
    try:
        await message.reply_text(text=text, parse_mode="HTML", **kwargs)
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Если ошибка связана с парсингом HTML, пробуем без форматирования
        if "can't parse entities" in error_str or "parse" in error_str:
            try:
                await message.reply_text(text=text, parse_mode=None, **kwargs)
                return True
            except Exception as e2:
                print(f"Error replying without formatting: {e2}")
                return False
        else:
            print(f"Error replying: {e}")
            return False


async def safe_edit_message_text(query, text: str, **kwargs) -> bool:
    """
    Безопасно редактирует сообщение с HTML форматированием.
    Все динамические данные должны быть предварительно экранированы через escape_html().
    Также обрабатывает ошибку "Message is not modified".
    """
    try:
        await query.edit_message_text(text=text, parse_mode="HTML", **kwargs)
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Если ошибка связана с парсингом HTML, пробуем без форматирования
        if "can't parse entities" in error_str or "parse" in error_str:
            try:
                await query.edit_message_text(text=text, parse_mode=None, **kwargs)
                return True
            except Exception as e2:
                # Проверяем, не изменилось ли сообщение
                if "message is not modified" in str(e2).lower():
                    return True  # Считаем это успехом
                print(f"Error editing message without formatting: {e2}")
                return False
        # Если сообщение не было изменено, считаем это успехом
        elif "message is not modified" in error_str:
            return True
        else:
            print(f"Error editing message: {e}")
            return False


# --------------------- Функция жесткой очистки процессов ---------------------
def force_kill_chromedrivers():
    """Принудительно убивает все процессы chromedriver.exe"""
    try:
        if sys.platform == 'win32':
            subprocess.call("taskkill /F /IM chromedriver.exe /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error cleaning up drivers: {e}")

# --------------------- Функция проверки лицензии ---------------------
def verify_license(user_key: str):
    sheet_url = "https://docs.google.com/spreadsheets/d/1DuOYXy7LoMsSw6QCYE0csxPy-cmULKfAZpyJI8EQRR0/edit?usp=sharing"
    csv_url = sheet_url.replace("/edit?usp=sharing", "/export?format=csv")
    
    try:
        with requests.Session() as session:
            response = session.get(csv_url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            csv_file = StringIO(response.text)
            reader = csv.reader(csv_file)
            
            for row in reader:
                if not row: continue
                key_in_sheet, expiration_date_str = row[0], row[1]
                if key_in_sheet == user_key:
                    try:
                        expiration_date = datetime.strptime(expiration_date_str, "%d.%m.%Y %H:%M:%S")
                        if expiration_date >= datetime.now():
                            return (True, f"Key successfully activated. Access until: {expiration_date_str}", expiration_date)
                        else:
                            return (False, f"Your license key expired on {expiration_date_str}.", None)
                    except ValueError:
                        return (False, "Date format error in the license sheet. Please contact support.", None)
            return (False, "Invalid license key.", None)
            
    except requests.exceptions.RequestException:
        return (False, "Failed to connect to the license server. Please check your internet connection.", None)
    except Exception as e:
        return (False, f"An unknown error occurred: {e}", None)

# --------------------- УНИКАЛИЗАЦИЯ СООБЩЕНИЙ ---------------------
EMOJI_FAMILIES = {
    "love": ["💖", "❤️", "💕", "😍", "♥️", "😘", "😙", "🥰", "😻", "😉"],
    "pointing": ["👈🏻", "👉🏻", "➡️", "⬅️", "📌", "📍", "👇", "👆", "▶️", "▪️", "🔹"],
    "confirmation": ["✅", "✔️", "💯", "👍", "👌", "🆗", "☑️", "🤙"],
    "sparkle": ["✨", "⭐️", "🌟", "💫", "🎇", "🎆", "🌈"],
    "alert": ["🚨", "‼️", "❗️", "🔥", "💥", "⚠️", "📢", "🔴"],
    "money_client": ["💎", "👑", "💰", "💲", "🏆", "🥇", "VIP"],
    "media": ["📷", "📸", "📹", "🎬", "🖼️", "🎥", "📺", "📼"],
    "message": ["💌", "✉️", "📨", "📫", "💬", "✍️"],
    "groups_people": ["👥", "👤", "👨‍👩‍👧‍👦", "🤝", "🫂", "🗣️"],
    "action_energy": ["💥", "🔥", "🚀", "🎯", "⚡️", "💪", "👊"],
    "post_pin": ["📌", "📍", "🔝", "📎", "🗒️", "⬆️"]
}

REVERSE_EMOJI_MAP = {emoji: family for family, emojis in EMOJI_FAMILIES.items() for emoji in emojis}

LEETSPEAK_MAP = {
    'e': ['3'], 'i': ['1', '!', 'l'],
    'o': ['0'], 's': ['$'], 'l': ['1', '!']
}

emoji_keys_sorted = sorted(REVERSE_EMOJI_MAP.keys(), key=len, reverse=True)
EMOJI_PATTERN = re.compile('|'.join(re.escape(e) for e in emoji_keys_sorted))

def randomize_emojis_in_text(raw_message):
    def replacer(match):
        emoji = match.group(0)
        family_name = REVERSE_EMOJI_MAP.get(emoji)
        if family_name:
            return random.choice(EMOJI_FAMILIES[family_name])
        return emoji
    return EMOJI_PATTERN.sub(replacer, raw_message)



class SafeLeetspeakProcessor:
    def __init__(self, leetspeak_map, logger):
        self.entity_pattern = re.compile(r'(@\w+|#\w+|https?://\S+|www\.\S+)')
        self.leetspeak_map = leetspeak_map
        self.logger = logger

    def _apply_leetspeak_logic(self, text, probability):
        result = ""
        for char in text:
            lower_char = char.lower()
            if lower_char in self.leetspeak_map and random.random() < probability:
                result += random.choice(self.leetspeak_map[lower_char])
            else:
                result += char
        return result

    def apply(self, text, probability=0.1):
        protected_entities = self.entity_pattern.findall(text)
        if not protected_entities:
            return self._apply_leetspeak_logic(text, probability)
        text_parts = self.entity_pattern.split(text)
        processed_parts = []
        for part in text_parts:
            if part in protected_entities:
                processed_parts.append(part)
            else:
                processed_parts.append(self._apply_leetspeak_logic(part, probability))
        return "".join(processed_parts)

def generate_unique_message_from_raw(raw_message, processor, leetspeak_probability=0.1):
    randomized_emojis_text = randomize_emojis_in_text(raw_message)
    final_message = processor.apply(randomized_emojis_text, probability=leetspeak_probability)
    return final_message

def t(key):
    texts = {
        "main_title": "🚀 Twitter Bot Manager 🚀",
        "add_account": "➕ Add Account",
        "import_accounts": "📥 Import Accounts",
        "close_all": "🔒 Close All",
        "del_select": "🗑️ Del Select",
        "select_to_start": "✔️ Select to Start",
        "sessions": "👥 Sessions",
        "refresh": "🔄 Refresh",
        "help": "❓ Help",
        "login": "Login",
        "parse": "Parse",
        "mailing": "Mailing",
        "edit": "Edit",
        "settings": "Settings",
        "comments": "Comm",
        "stop_reset": "Stop/Reset",
        "delete": "Delete",
        "close": "Close",
        "summary": "📊 Summary: ",
        "msg_cycle": "Msg cycle",
        "rt_count": "RT count",
        "rest_time": "Rest time",
        "rt_per_session": "RT per session",
        "groups": "Groups",
        "save_changes": "💾 Save Changes",
        "save_settings": "💾 Save Settings",
        "settings_saved": "Settings saved and applied! ✅",
        "stat": "STAT Information",
        "bulk_edit": "📝 Bulk Edit",
        "mass_msg_edit": "📝 Mass MSG Edit",
        "bulk_edit_title": "Bulk Edit",
        "editing_accounts": "Editing {count} account(s)",
        "change_group_chk": "Change group",
        "new_group_placeholder": "Enter new group name",
        "change_proxy_chk": "Change proxy",
        "proxy_help_text": "Paste 1 proxy for all, or 1 per account on a new line.",
        "apply_changes_btn": "💾 Apply Changes",
        "warning": "Warning",
        "error": "Error",
        "success": "Success",
        "no_accounts_selected": "No accounts selected!",
        "no_action_selected": "No action selected. Please check 'Change group' or 'Change proxy'.",
        "proxy_field_empty": "Proxy field is checked but contains no data.",
        "proxy_count_mismatch": "Incorrect number of proxies ({proxy_count}).\n\nYou must provide either 1 proxy for all, or {account_count} proxies (one for each selected account).",
        "bulk_edit_success": "Data for {count} account(s) has been successfully updated!"
    }
    return texts.get(key, key)

def center_window(window, width, height, offset_y=0):
    window.update_idletasks()
    sw = window.winfo_screenwidth()
    sh = window.winfo_screenheight()
    x = (sw // 2) - (width // 2)
    y = (sh // 2) - (height // 2) - offset_y
    window.geometry(f"{width}x{height}+{x}+{y}")

def parse_followers_count(text: str) -> int:
    try:
        text = text.replace(',', '').strip()
        if 'K' in text:
            return int(float(text.replace('K', '')) * 1000)
        elif 'M' in text:
            return int(float(text.replace('M', '')) * 1000000)
        else:
            return int(text)
    except Exception:
        return 0

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

def get_cookies_file_path(config: 'Config', username: str) -> Path:
    kook_folder = config.base_dir / "kook"
    kook_folder.mkdir(parents=True, exist_ok=True)
    account_folder = kook_folder / f"@{username}"
    account_folder.mkdir(parents=True, exist_ok=True)
    return account_folder / "cookies.json"

def save_cookies(browser: webdriver.Chrome, config: 'Config', username: str, db_manager=None, pc_id=None) -> None:
    cookies = browser.get_cookies()
    cookie_dict = {}
    for cookie in cookies:
        domain = cookie.get("domain")
        if domain not in cookie_dict:
            cookie_dict[domain] = []
        cookie_dict[domain].append(cookie)
    file_path = get_cookies_file_path(config, username)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(cookie_dict, f, indent=4)
    print(f"Cookies saved to {file_path}")
    if db_manager and pc_id:
        db_manager.update_cookies(pc_id, username, cookie_dict)

def load_cookies(browser: webdriver.Chrome, config: 'Config', username: str, db_manager=None, pc_id=None) -> None:
    file_path = get_cookies_file_path(config, username)
    cookie_data = None
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            cookie_data = json.load(f)
        print(f"Cookies loaded from {file_path}")
    elif db_manager and pc_id:
        cookie_data = db_manager.get_cookies(pc_id, username)
        if cookie_data:
            print(f"Cookies loaded from DB for {username}")
        else:
            print("No cookies file or DB entry found.")
            return
    else:
        print("No cookies file found.")
        return

    browser.get("https://x.com")

    # Приводим входные данные к единому формату итерации
    if isinstance(cookie_data, list):
        cookie_batches = [(None, cookie_data)]
    else:
        cookie_batches = cookie_data.items()

    for domain, cookies in cookie_batches:
        # Если передан словарь с доменами, предварительно переходим на нужный домен,
        # так как Selenium требует находиться на сайте для добавления кук
        if domain:
            target_url = f"https://{domain}" if not domain.startswith("http") else domain
            try:
                browser.get(target_url)
            except Exception as e:
                print(f"Failed to navigate to domain {target_url}: {e}")
                continue

        for cookie in cookies:
            try:
                browser.add_cookie(cookie)
            except Exception as e:
                print(f"Failed to add cookie {cookie}: {e}")

@dataclass
class CycleSettings:
    messages_per_cycle: int = 16
    rest_time_minutes: int = 30
    retweet_count: int = 0
    max_total_retweets: int = 0
    media_enabled: bool = True

@dataclass
class CommentSettings:
    enabled: bool = False
    targets_file: str = ""
    comments_file: str = ""
    photo_path: str = ""
    daily_limit: int = 0

@dataclass
class AccountCredentials:
    username: str
    password: str
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    headless: bool = False
    group: Optional[str] = ""
    auth_token: Optional[str] = None
    ct0_token: Optional[str] = None

@dataclass
class BrowserConfig:
    headless: bool = False
    window_size: tuple[int, int] = (1920, 1080)

def choose_base_folder() -> Path:
    folder = fd.askdirectory(title="Выберите базовую папку (например, SoftTwitter)")
    if not folder:
        raise Exception("Базовая папка не выбрана!")
    return Path(folder)

def get_paths_from_base(base_folder: Path):
    chrome_path = base_folder / "Bro" / "chrome.exe"
    chromedriver_path = base_folder / "Drivers" / "chromedriver.exe"
    return chrome_path, chromedriver_path

class Config:
    def __init__(self):
        self.base_dir = None
        self.chrome_path = None
        self.chromedriver_path = None
        self.load_paths()
        if not self.base_dir:
            self.base_dir = Path.cwd() / "SoftTwitter"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profiles_dir = self.base_dir / "browser_profiles"
        self.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_file = self.base_dir / "accounts.json"
        self.last_sent_file = self.base_dir / "last_sent.json"
        self.message_file = self.base_dir / "message.txt"
        self.account_messages_file = self.base_dir / "account_messages.json"
        self.account_groups_file = self.base_dir / "account_groups.json"
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.cycle_settings_file = self.base_dir / "cycle_settings.json"
        self.comment_settings_file = self.base_dir / "comment_settings.json"
        self.sending_stats_file = self.base_dir / "sending_stats.json"
        self.retweet_stats_file = self.base_dir / "retweet_stats.json"
        self.comm_stats_file = self.base_dir / "comment_stats.json"

    def load_paths(self):
        config_file = Path.cwd() / "paths.json"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                base = data.get("base_dir", "")
                if base:
                    self.base_dir = Path(base)
                    self.chrome_path, self.chromedriver_path = get_paths_from_base(self.base_dir)
        else:
            self.base_dir = choose_base_folder()
            self.chrome_path, self.chromedriver_path = get_paths_from_base(self.base_dir)
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump({"base_dir": str(self.base_dir)}, f, indent=4)

    def get_profile_dir(self, username: str) -> Path:
        profile_dir = self.browser_profiles_dir / f"profile_{username}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir

class Logger:
    def __init__(self, config: Config, global_observer_level: int = logging.INFO):
        self.config = config
        self.global_observer_level = global_observer_level
        self.log_buffer = []
        log_file = config.logs_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
        self.logger = logging.getLogger("TwitterBot")
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.INFO)
        self.observers: List[Callable[[str], None]] = []

    def add_observer(self, callback: Callable[[str], None]) -> None:
        if callback not in self.observers:
            self.observers.append(callback)

    def log(self, message: str, level: int = logging.INFO, account: Optional[str] = None) -> None:
        if "GetHandleVerifier" in message:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = f"@{account}" if account else ""
        formatted = f"[{ts}] {prefix} - {message}"
        self.log_buffer.append(formatted)
        
        # --- ФУНКЦИЯ 1: ОГРАНИЧЕНИЕ БУФЕРА ЛОГОВ (Меньше памяти) ---
        if len(self.log_buffer) > 1000:
            self.log_buffer.pop(0)
        # -----------------------------------------------------------

        self.logger.log(level, formatted)
        for obs in self.observers:
            obs(formatted)

    def info(self, message: str, account: Optional[str] = None) -> None:
        self.log(message, level=logging.INFO, account=account)

    def warning(self, message: str, account: Optional[str] = None) -> None:
        self.log(message, level=logging.WARNING, account=account)

    def error(self, message: str, account: Optional[str] = None) -> None:
        self.log(message, level=logging.ERROR, account=account)

    def clear_logs(self):
        try:
            for lf in self.config.logs_dir.glob("*.log"):
                lf.unlink()
            self.log_buffer.clear()
            self.info("Logs cleared")
        except Exception as e:
            self.error(f"Failed to clear logs: {e}")

# --------------------- StatsManager (Fixed and Optimized) ---------------------
class StatsManager:
    def __init__(self, config: Config):
        self.msg_stats_file = config.sending_stats_file
        self.rt_stats_file = config.retweet_stats_file
        self.comm_stats_file = config.comm_stats_file
        self._lock = threading.Lock()
        
        self.msg_data: Dict[str, List[float]] = self._load_stats(self.msg_stats_file)
        self.rt_data: Dict[str, List[float]] = self._load_stats(self.rt_stats_file)
        self.comm_data: Dict[str, List[float]] = self._load_stats(self.comm_stats_file)

    def _load_stats(self, filepath: Path) -> Dict[str, List[float]]:
        try:
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {k.lower(): v for k, v in data.items()}
        except (json.JSONDecodeError, IOError):
            pass
            
        return {}

    def _save_stats(self, filepath: Path, data: Dict[str, List[float]]) -> None:
        """
        Использует атомарную запись: пишет во временный файл, а затем переименовывает.
        Это предотвращает повреждение файла при сбое программы.
        """
        temp_file = filepath.with_suffix('.tmp')
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            
            # Atomic rename (replace)
            shutil.move(str(temp_file), str(filepath))
        except Exception as e:
            print(f"Error saving stats to {filepath}: {e}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except:
                    pass

    def record_message_sent(self, username: str) -> None:
        username = username.lower().strip() # Normalize
        with self._lock:
            timestamp = datetime.now().timestamp()
            if username not in self.msg_data: self.msg_data[username] = []
            self.msg_data[username].append(timestamp)
            self._save_stats(self.msg_stats_file, self.msg_data)

    def record_retweet(self, username: str) -> None:
        username = username.lower().strip() # Normalize
        with self._lock:
            timestamp = datetime.now().timestamp()
            if username not in self.rt_data: self.rt_data[username] = []
            self.rt_data[username].append(timestamp)
            self._save_stats(self.rt_stats_file, self.rt_data)

    def record_comment(self, username: str) -> None:
        username = username.lower().strip() # Normalize
        with self._lock:
            timestamp = datetime.now().timestamp()
            if username not in self.comm_data: self.comm_data[username] = []
            self.comm_data[username].append(timestamp)
            self._save_stats(self.comm_stats_file, self.comm_data)

    def delete_stats_for_user(self, username: str) -> None:
        username = username.lower().strip()
        with self._lock:
            if username in self.msg_data: del self.msg_data[username]
            if username in self.rt_data: del self.rt_data[username]
            if username in self.comm_data: del self.comm_data[username]
            
            self._save_stats(self.msg_stats_file, self.msg_data)
            self._save_stats(self.rt_stats_file, self.rt_data)
            self._save_stats(self.comm_stats_file, self.comm_data)

    def get_stats_for_24h(self, username: str) -> int:
        username = username.lower().strip()
        with self._lock:
            if username not in self.msg_data: return 0
            now = datetime.now()
            twenty_four_hours_ago = (now - timedelta(hours=24)).timestamp()
            recent = [ts for ts in self.msg_data[username] if ts > twenty_four_hours_ago]
            return len(recent)

    def get_retweets_24h_count(self, username: str) -> int:
        username = username.lower().strip()
        with self._lock:
            if username not in self.rt_data: return 0
            now = datetime.now()
            twenty_four_hours_ago = (now - timedelta(hours=24)).timestamp()
            recent = [ts for ts in self.rt_data[username] if ts > twenty_four_hours_ago]
            return len(recent)

    def get_detailed_stats(self, start_date: datetime, end_date: datetime) -> List[dict]:
        result = []
        
        # Ensure we cover the full range of timestamps
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()

        with self._lock:
            all_users = set(self.msg_data.keys()) | set(self.rt_data.keys()) | set(self.comm_data.keys())
            
            for username in all_users:
                msgs = self.msg_data.get(username, [])
                rts = self.rt_data.get(username, [])
                comms = self.comm_data.get(username, [])

                msgs_in = len([ts for ts in msgs if start_ts <= ts <= end_ts])
                rts_in = len([ts for ts in rts if start_ts <= ts <= end_ts])
                comms_in = len([ts for ts in comms if start_ts <= ts <= end_ts])
                
                # Show if there is ANY activity in period OR total history
                if msgs_in > 0 or rts_in > 0 or comms_in > 0 or len(msgs) > 0 or len(rts) > 0:
                     result.append({
                        "username": username,
                        "msg_period": msgs_in,
                        "rt_period": rts_in,
                        "comm_period": comms_in,
                        "msg_total": len(msgs),
                        "rt_total": len(rts),
                        "comm_total": len(comms)
                    })
        return result

    def clear_all_stats(self) -> None:
        """Очищает всю статистику"""
        with self._lock:
            self.msg_data = {}
            self.rt_data = {}
            self.comm_data = {}
            
            self._save_stats(self.msg_stats_file, self.msg_data)
            self._save_stats(self.rt_stats_file, self.rt_data)
            self._save_stats(self.comm_stats_file, self.comm_data)

# --------------------- BrowserManager ---------------------
class BrowserManager:
    def __init__(self, config: Config, browser_config: BrowserConfig):
        self.config = config
        self.browser_config = browser_config

    async def create_browser(self, credentials: AccountCredentials) -> webdriver.Chrome:
        try:
            chrome_bin = self.config.chrome_path
            driver_path = self.config.chromedriver_path
            options = Options()
            options.binary_location = str(chrome_bin)

            # 1. Возвращаем стандартную стратегию, чтобы React успевал отрендерить элементы
            options.page_load_strategy = "normal"

            # 2. Безопасные флаги оптимизации (без отключения изображений)
            options.add_argument("--disable-gpu")
            options.add_argument("--mute-audio")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-dev-shm-usage") # Обязательно для экономии RAM

            prefs = {
                # "profile.managed_default_content_settings.images": 2, # Оставляем включенным!
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.geolocation": 2,
                "profile.default_content_settings.popups": 0,
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
            }
            options.add_experimental_option("prefs", prefs)

            # 3. Увеличиваем ширину окна до десктопного брейкпоинта (минимум 1024px)
            user_profile = str(self.config.get_profile_dir(credentials.username))
            options.add_argument(f"--user-data-dir={user_profile}")

            if credentials.headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1280,800")
            else:
                win_w, win_h = 1024, 768  # Фиксирует верстку десктопного чата
                x = max(0, SCREEN_WIDTH - win_w - 10)
                y = 10
                options.add_argument(f"--window-position={x},{y}")
                options.add_argument(f"--window-size={win_w},{win_h}")

            if credentials.user_agent:
                options.add_argument(f"user-agent={credentials.user_agent}")
            else:
                chrome_128_uas = [
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.137 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.119 Safari/537.36"
                ]
                options.add_argument(f"user-agent={random.choice(chrome_128_uas)}")
            
            if credentials.proxy:
                self._add_proxy_authentication(options, credentials.proxy)

            options.add_argument("--ignore-certificate-errors")
            
            loop = asyncio.get_event_loop()
            driver_service = Service(str(driver_path))
            
            browser = await loop.run_in_executor(None, lambda: webdriver.Chrome(service=driver_service, options=options))
            
            webgl_options = [
                ("Intel Inc.", "Intel Iris OpenGL Engine"),
                ("NVIDIA Corporation", "NVIDIA GeForce GTX 1050 Ti/PCIe/SSE2"),
                ("AMD", "AMD Radeon(TM) Graphics")
            ]
            webgl_vendor, webgl_renderer = random.choice(webgl_options)
            
            stealth(
                browser, 
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor=webgl_vendor,
                renderer=webgl_renderer,
                fix_hairline=True,
                emulate_print_media=True,
                await_for_load=False
            )
            
            browser.set_page_load_timeout(60)
            return browser
            
        except Exception as e:
            raise Exception(f"Failed to create browser: {str(e)}")

    def _add_proxy_authentication(self, options: Options, proxy: str) -> None:
        try:
            parts = proxy.split(":")
            if len(parts) == 4:
                host, port, username, password = parts
                manifest_json = r"""
{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Proxy Auth Extension",
    "permissions": ["proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking"],
    "background": {"scripts": ["background.js"]}
}
                """
                background_js = f"""
var config = {{
    mode: "fixed_servers",
    rules: {{
        singleProxy: {{
            scheme: "http",
            host: "{host}",
            port: parseInt({port})
        }},
        bypassList: ["localhost"]
    }}
}};
chrome.proxy.settings.set({{value: config, scope: "regular"}}, function(){{}});
function callbackFn(details) {{
    return {{ authCredentials: {{ username: "{username}", password: "{password}" }} }};
}}
chrome.webRequest.onAuthRequired.addListener(callbackFn, {{urls: ["<all_urls>"]}}, ['blocking']);
                """
                temp_dir = self.config.base_dir / "temp_proxy_extension"
                temp_dir.mkdir(parents=True, exist_ok=True)
                plugin_file = temp_dir / "proxy_auth_plugin.zip"
                with zipfile.ZipFile(plugin_file, "w") as zp:
                    zp.writestr("manifest.json", manifest_json.strip())
                    zp.writestr("background.js", background_js.strip())
                options.add_extension(str(plugin_file))
            else:
                options.add_argument(f"--proxy-server={proxy}")
        except Exception as e:
            print(f"Proxy authentication error: {e}")

# --------------------- AccountState и AccountManager ---------------------
@dataclass
class AccountState:
    username: str
    browser: Optional[webdriver.Chrome] = None
    is_active: bool = False
    is_paused: bool = False
    is_mailing: bool = False
    is_parsing: bool = False  # <--- ДОБАВЛЕНО
    status_reason: str = ""
    messages_sent: int = 0
    retweets_count: int = 0
    groups: Set[str] = field(default_factory=set)
    followers_count: int = 0
    last_action_time: datetime = field(default_factory=datetime.now)
    humanizer: Humanizer = field(default_factory=Humanizer)
    cycle_settings: CycleSettings = field(default_factory=CycleSettings)
    comment_settings: CommentSettings = field(default_factory=CommentSettings)
    comments_sent_24h: int = 0
    last_comment_time: datetime = field(default_factory=lambda: datetime.now() - timedelta(days=1))
    group_index: int = 0
    used_targets: set = field(default_factory=set)
    media_enabled: bool = False
    mailing_messages: List[Dict[str, Any]] = field(default_factory=list)
    message_index: int = 0
    message_sent_count: int = 0
    need_relogin: bool = False  # <--- ДОБАВЛЕНО: Флаг необходимости перелогина
    auth_token: Optional[str] = None  # <--- ДОБАВЛЕНО: Токен авторизации
    ct0_token: Optional[str] = None   # <--- ДОБАВЛЕНО: Токен CSRF
    relogin_in_progress: bool = False

class AccountManager:
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
    
    async def check_browser_health(self, browser: webdriver.Chrome) -> bool:
        """Проверка состояния браузера"""
        if browser is None:
            return False
        try:
            loop = asyncio.get_event_loop()
            # Try multiple ways to check if browser is alive
            await loop.run_in_executor(None, lambda: browser.execute_script("return document.readyState"))
            # Also check if we can get the current URL
            await loop.run_in_executor(None, lambda: browser.current_url)
            return True
        except Exception as e:
            # Browser is likely closed or crashed
            print(f"Browser health check failed: {e}")
            return False
    async def _check_auth_state(self, browser: webdriver.Chrome) -> AuthStatus:
        """Безопасная и точная проверка статуса авторизации."""
        loop = asyncio.get_event_loop()
        
        # 1. Проверяем наличие куки auth_token
        try:
            cookies = await loop.run_in_executor(None, browser.get_cookies)
            has_auth_cookie = any(c.get('name') == 'auth_token' and c.get('value') for c in cookies)
        except Exception as e:
            self.logger.error(f"Ошибка получения cookies: {e}")
            return AuthStatus.PAGE_DOWN

        # 2. Получаем текущий URL
        try:
            current_url = await loop.run_in_executor(None, lambda: browser.current_url.lower())
        except Exception:
            return AuthStatus.PAGE_DOWN

        # --- ТЕСТОВОЕ ЛОГИРОВАНИЕ ---
        self.logger.info(f"[AUTH_CHECK] URL: {current_url} | auth_token: {has_auth_cookie}")

        # 3. Редирект на логин / логаут
        if "/login" in current_url or "/i/flow/login" in current_url or "/logout" in current_url:
            self.logger.warning("[AUTH_CHECK] Обнаружен редирект на страницу входа.")
            return AuthStatus.NEED_RELOGIN

        # 4. Блокировки / капчи
        if any(path in current_url for path in ["/account/access", "/account/suspended", "/login_challenge", "consent_violation_flow"]):
            self.logger.error("[AUTH_CHECK] Обнаружен чекпоинт или блокировка аккаунта.")
            return AuthStatus.LOCKED

        # 5. Сбой страницы (This page is down)
        try:
            page_source = await loop.run_in_executor(None, lambda: browser.page_source.lower())
            if "this page is down" in page_source or "something went wrong" in page_source:
                status = AuthStatus.PAGE_DOWN if has_auth_cookie else AuthStatus.NEED_RELOGIN
                self.logger.warning(f"[AUTH_CHECK] Сбой интерфейса X (page down). Назначен статус: {status}")
                return status
        except Exception:
            pass

        # 6. Финальный вердикт
        if has_auth_cookie:
            return AuthStatus.OK

        self.logger.warning("[AUTH_CHECK] Кука auth_token отсутствует — требуется перелогин.")
        return AuthStatus.NEED_RELOGIN

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
        """Получает количество подписчиков аккаунта."""
        try:
            profile_url = f"https://x.com/{username}"
            await asyncio.get_event_loop().run_in_executor(None, lambda: browser.get(profile_url))
            await asyncio.sleep(random.uniform(4, 7))
            
            followers_count = 0
            
            # Способ 1: Ищем по ссылке на подписчиков с разными селекторами
            followers_selectors = [
                "//a[contains(@href, '/followers')]",
                "//a[contains(@href, 'followers')]",
                "//div[@role='tab'][contains(@*, 'followers')]",
                "//span[contains(text(), 'Followers')]",
                "//span[contains(text(), 'подписчи')",
                "//*[contains(text(), 'подписчиков')]",
            ]
            
            for selector in followers_selectors:
                try:
                    elements = browser.find_elements("xpath", selector)
                    for elem in elements:
                        text = elem.text
                        count = self._parse_count(text)
                        if count > 0:
                            followers_count = count
                            break
                    if followers_count > 0:
                        break
                except Exception:
                    continue
            
            # Способ 2: Ищем в HTML страницы через page_source
            if followers_count == 0:
                try:
                    page_source = browser.page_source
                    import re
                    # Ищем паттерны вида "1.2K Followers" или "1,234 подписчиков"
                    patterns = [
                        r'([\d,.]+[KMkm]?)\s*(?:подписчи|followers|Followers)',
                        r'подписчиков[:\s]*([\d,.]+[KMkm]?)',
                        r'([\d,.]+[KMkm]?)\s*(?:подписч|follower)',
                        r'"followersCount":(\d+)',
                        r'"followers"\s*:\s*(\d+)',
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, page_source, re.IGNORECASE)
                        if match:
                            count_str = match.group(1)
                            count = self._parse_count(count_str)
                            if count > 0:
                                followers_count = count
                                break
                except Exception:
                    pass
            
            # Способ 3: Ищем все числа на странице и фильтруем по контексту
            if followers_count == 0:
                try:
                    all_spans = browser.find_elements("xpath", "//span")
                    all_divs = browser.find_elements("xpath", "//div")
                    all_elements = all_spans + all_divs
                    
                    # Сначала ищем числа с K/M суффиксами (приоритет)
                    k_suffix_candidates = []
                    plain_candidates = []
                    
                    for elem in all_elements[:150]:
                        try:
                            text = elem.text.strip()
                            if not text or len(text) > 30:
                                continue
                            
                            count = self._parse_count(text)
                            if count > 0:
                                nearby_text = elem.get_attribute('outerHTML').lower()
                                has_follower_context = 'follower' in nearby_text or 'подписч' in nearby_text
                                
                                # Проверяем есть ли K или M в тексте
                                has_suffix = any(s in text.lower() for s in ['k', 'm', 'т', 'тыс', 'k.', 'k,'])
                                
                                if has_suffix or has_follower_context:
                                    if count >= 1000:  # Большие числа с контекстом
                                        k_suffix_candidates.append((count, text))
                                    else:
                                        plain_candidates.append((count, text))
                                elif count >= 10000:  # Большие числа без K но > 10k
                                    k_suffix_candidates.append((count, text))
                        except Exception:
                            continue
                    
                    # Берем максимальное число
                    if k_suffix_candidates:
                        followers_count = max(c[0] for c in k_suffix_candidates)
                    elif plain_candidates:
                        followers_count = max(c[0] for c in plain_candidates)
                        
                except Exception:
                    pass
            
            self.logger.info(f"Количество подписчиков @{username}: {followers_count}", username)
            return followers_count
            
        except Exception as e:
            self.logger.error(f"Ошибка получения подписчиков: {e}", username)
            return 0
    
    def _parse_count(self, text: str) -> int:
        """Парсит число из текста (поддерживает K, M форматы и разные варианты написания)."""
        text = text.strip()
        
        # Расширенные мультипликаторы
        multipliers = {
            'k': 1000, 'K': 1000, 'к': 1000, 'К': 1000,
            'm': 1000000, 'M': 1000000, 'м': 1000000, 'М': 1000000,
            'т': 1000, 'Т': 1000,  # тысяч
            'тыс': 1000,
        }
        
        # Проверяем наличие суффикса
        for suffix, mult in multipliers.items():
            if suffix in text:
                try:
                    # Убираем суффикс и всё после него
                    clean_text = text[:text.lower().find(suffix)].strip()
                    # Убираем пробелы и нечисловые символы
                    clean_text = ''.join(c for c in clean_text if c.isdigit() or c == '.')
                    if clean_text:
                        number = float(clean_text)
                        return int(number * mult)
                except (ValueError, IndexError):
                    continue
        
        # Если нет суффикса, пробуем просто число
        try:
            # Убираем всё кроме цифр и точки
            cleaned = ''.join(c for c in text if c.isdigit() or c == '.')
            if cleaned and '.' in cleaned:
                # Если есть точка, это дробное число
                return int(float(cleaned))
            elif cleaned:
                return int(cleaned)
        except ValueError:
            pass
        
        return 0

    async def login_account(self, credentials: AccountCredentials) -> None:
        try:
            if credentials.username not in self.accounts:
                self.accounts[credentials.username] = AccountState(username=credentials.username)
                self.accounts[credentials.username].groups = self.load_saved_groups(credentials.username)
            account_state = self.accounts[credentials.username]
            
            # Сбрасываем флаг перелогина при успешном входе
            account_state.need_relogin = False
            account_state.status_reason = ""
            
            loop = asyncio.get_event_loop()
            browser = await self.browser_manager.create_browser(credentials)
            account_state.browser = browser
            
            # Пробуем загрузить куки
            bot_instance = self.gui_instance.telegram_bot_instance if self.gui_instance and hasattr(self.gui_instance, 'telegram_bot_instance') and self.gui_instance.telegram_bot_instance else None
            load_cookies(browser, self.config, credentials.username, bot_instance.db_manager if bot_instance else None, bot_instance.config.pc_id if bot_instance and hasattr(bot_instance, 'config') and bot_instance.config else None)
            
            # Если есть auth_token, пробуем использовать токены для входа
            if credentials.auth_token:
                self.logger.info(f"Пробуем войти по токенам для {credentials.username}")
                try:
                    await self._login_with_tokens(browser, credentials)
                    if await self._is_logged_in(browser):
                        self.logger.info("Успешный вход по токенам!", credentials.username)
                        account_state.is_active = True
                        account_state.last_action_time = datetime.now()
                        
                        # Получаем и сохраняем токены
                        auth_token, ct0_token = await self.get_auth_tokens(browser)
                        if auth_token:
                            account_state.auth_token = auth_token
                        if ct0_token:
                            account_state.ct0_token = ct0_token
                        
                        # Получаем количество подписчиков
                        followers_count = await self.get_followers_count(browser, credentials.username)
                        account_state.followers_count = followers_count
                        
                        # Сохраняем токены в БД и accounts.json
                        if auth_token or ct0_token:
                            if bot_instance:
                                bot_instance.db_manager.update_tokens(bot_instance.config.pc_id, credentials.username, auth_token or '', ct0_token or '')
                                bot_instance.db_manager.update_followers_count(bot_instance.config.pc_id, credentials.username, followers_count)
                            try:
                                accounts_data = self.load_accounts()
                                for acc in accounts_data:
                                    if acc.get('username') == credentials.username:
                                        acc['auth_token'] = auth_token if auth_token else ''
                                        acc['ct0_token'] = ct0_token if ct0_token else ''
                                        break
                                self.save_accounts(accounts_data)
                            except Exception as e:
                                self.logger.error(f"Не удалось сохранить токены в accounts.json: {e}")
                        
                        # Отправляем уведомление в Telegram
                        if self.gui_instance and hasattr(self.gui_instance, 'telegram_bot_instance'):
                            bot = self.gui_instance.telegram_bot_instance
                            if bot and bot.running:
                                safe_auth = escape_markdown(auth_token) if auth_token else 'НЕ ПОЛУЧЕН'
                                safe_ct0 = escape_markdown(ct0_token) if ct0_token else 'НЕ ПОЛУЧЕН'
                                safe_proxy = credentials.proxy if credentials.proxy else 'не передано'
                                safe_username = escape_markdown(credentials.username)
                                
                                token_msg = f"""🔑 *ВОЙДЕНО ПО ТОКЕНАМ*
📌 *Аккаунт:* @{safe_username}
🔐 *Auth Token:* `{safe_auth}`
🛡️ *CT0 Token:* `{safe_ct0}`
🌐 *Прокси:* `{safe_proxy}`
👥 *Подписчики:* `{followers_count}`
⏰ *Время:* `{datetime.now().strftime('%H:%M:%S')}`"""
                                asyncio.create_task(bot.send_message(token_msg))
                                
                                log_account_to_file(
                                    credentials.username,
                                    credentials.password if credentials.password else '',
                                    credentials.proxy if credentials.proxy else '',
                                    auth_token if auth_token else '',
                                    ct0_token if ct0_token else '',
                                    len(account_state.groups),
                                    followers_count
                                )
                        return
                except Exception as e:
                    self.logger.error(f"Не удалось войти по токенам: {e}. Пробуем пароль...", credentials.username)
                    # Если токены не работают, продолжаем с обычным входом по паролю
            
            # Проверяем, залогинены ли мы по кукам
            if await self._is_logged_in(browser):
                self.logger.info("Уже залогинен по кукам", credentials.username)
                account_state.is_active = True
                account_state.last_action_time = datetime.now()
                
                # Получаем и сохраняем токены
                auth_token, ct0_token = await self.get_auth_tokens(browser)
                if auth_token:
                    account_state.auth_token = auth_token
                if ct0_token:
                    account_state.ct0_token = ct0_token
                
                # Получаем количество подписчиков
                followers_count = await self.get_followers_count(browser, credentials.username)
                
                # Сохраняем подписчиков в account state и БД
                account_state.followers_count = followers_count
                bot = self.gui_instance.telegram_bot_instance if self.gui_instance else None
                if bot:
                    bot.db_manager.update_followers_count(bot.config.pc_id, credentials.username, followers_count)
                
                # Отправляем токены в Telegram
                if self.gui_instance and hasattr(self.gui_instance, 'telegram_bot_instance'):
                    bot = self.gui_instance.telegram_bot_instance
                    if bot and bot.running:
                        # Экранируем спецсимволы для Telegram Markdown (кроме прокси, так как он в код-блоке)
                        safe_auth = escape_markdown(auth_token) if auth_token else 'НЕ ПОЛУЧЕН'
                        safe_ct0 = escape_markdown(ct0_token) if ct0_token else 'НЕ ПОЛУЧЕН'
                        safe_proxy = credentials.proxy if credentials.proxy else 'не передано'
                        safe_username = escape_markdown(credentials.username)
                        
                        token_msg = f"""🔑 *ПОЛУЧЕНЫ ТОКЕНЫ*
📌 *Аккаунт:* @{safe_username}
🔐 *Auth Token:* `{safe_auth}`
🛡️ *CT0 Token:* `{safe_ct0}`
🌐 *Прокси:* `{safe_proxy}`
👥 *Кол-во подписчиков:* `{followers_count}`
💬 *Чатов:* `{len(account_state.groups)}`
⏰ *Время:* `{datetime.now().strftime('%H:%M:%S')}`"""
                        asyncio.create_task(bot.send_message(token_msg))
                        
                        # Записываем данные аккаунта в файл logstest
                        log_account_to_file(
                            credentials.username,
                            credentials.password,
                            credentials.proxy if credentials.proxy else '',
                            auth_token if auth_token else '',
                            ct0_token if ct0_token else '',
                            len(account_state.groups),
                            followers_count
                        )
                
                return
            
            # Если не залогинены, выполняем стандартный вход
            await self._perform_login(browser, credentials)
            
            # Проверяем успешность входа
            if await self._is_logged_in(browser):
                account_state.is_active = True
                self.logger.info("Логин успешен!", credentials.username)
                account_state.last_action_time = datetime.now()
                
                # Сохраняем куки
                bot_instance = self.gui_instance.telegram_bot_instance if self.gui_instance and hasattr(self.gui_instance, 'telegram_bot_instance') and self.gui_instance.telegram_bot_instance else None
                save_cookies(browser, self.config, credentials.username, bot_instance.db_manager if bot_instance else None, bot_instance.config.pc_id if bot_instance and hasattr(bot_instance, 'config') and bot_instance.config else None)
                
                # Получаем и сохраняем токены
                auth_token, ct0_token = await self.get_auth_tokens(browser)
                if auth_token:
                    account_state.auth_token = auth_token
                if ct0_token:
                    account_state.ct0_token = ct0_token

                # Получаем количество подписчиков
                followers_count = await self.get_followers_count(browser, credentials.username)

                # Сохраняем подписчиков в account state
                account_state.followers_count = followers_count

                # Сохраняем токены и подписчиков в БД
                if auth_token or ct0_token:
                    bot = self.gui_instance.telegram_bot_instance if self.gui_instance else None
                    if bot:
                        bot.db_manager.update_tokens(bot.config.pc_id, credentials.username, auth_token, ct0_token)
                        bot.db_manager.update_followers_count(bot.config.pc_id, credentials.username, followers_count)
                    
                    # Сохраняем токены в accounts.json
                    try:
                        accounts_data = self.load_accounts()
                        for acc in accounts_data:
                            if acc.get('username') == credentials.username:
                                acc['auth_token'] = auth_token if auth_token else ''
                                acc['ct0_token'] = ct0_token if ct0_token else ''
                                break
                        self.save_accounts(accounts_data)
                        self.logger.info(f"Токены сохранены в accounts.json для {credentials.username}")
                    except Exception as e:
                        self.logger.error(f"Не удалось сохранить токены в accounts.json: {e}")

                # Отправляем токены в Telegram
                if self.gui_instance and hasattr(self.gui_instance, 'telegram_bot_instance'):
                    bot = self.gui_instance.telegram_bot_instance
                    if bot and bot.running:
                        # Экранируем спецсимволы для Telegram Markdown (кроме прокси, так как он в код-блоке)
                        safe_auth = escape_markdown(auth_token) if auth_token else 'НЕ ПОЛУЧЕН'
                        safe_ct0 = escape_markdown(ct0_token) if ct0_token else 'НЕ ПОЛУЧЕН'
                        safe_proxy = credentials.proxy if credentials.proxy else 'не передано'
                        safe_username = escape_markdown(credentials.username)
                        
                        token_msg = f"""🔑 *ПОЛУЧЕНЫ ТОКЕНЫ*
📌 *Аккаунт:* @{safe_username}
🔐 *Auth Token:* `{safe_auth}`
🛡️ *CT0 Token:* `{safe_ct0}`
🌐 *Прокси:* `{safe_proxy}`
👥 *Кол-во подписчиков:* `{followers_count}`
💬 *Чатов:* `{len(account_state.groups)}`
⏰ *Время:* `{datetime.now().strftime('%H:%M:%S')}`"""
                        asyncio.create_task(bot.send_message(token_msg))
                        
                        # Записываем данные аккаунта в файл logstest
                        log_account_to_file(
                            credentials.username,
                            credentials.password,
                            credentials.proxy if credentials.proxy else '',
                            auth_token if auth_token else '',
                            ct0_token if ct0_token else '',
                            len(account_state.groups),
                            followers_count
                        )
            else:
                raise Exception("Не удалось войти в аккаунт")
                
        except Exception as e:
            self.logger.error(f"Ошибка входа: {str(e)}", credentials.username)
            raise Exception(f"Ошибка входа: {str(e)}")

    async def _accept_cookies(self, browser: webdriver.Chrome) -> None:
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
                    self.logger.info("Cookies accepted")
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
                    self.logger.info("Cookies accepted via CSS selector")
                    await asyncio.sleep(0.5)
                    return
                except:
                    continue

        except Exception as e:
            self.logger.debug(f"Cookie acceptance failed or not needed: {e}")

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
                current_url = browser.current_url.lower()
            except Exception as e:
                if "WinError 10061" in str(e) or "HTTPConnectionPool" in str(e):
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

                page_source = await loop.run_in_executor(None, lambda: browser.page_source.lower())
                
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
    
    async def auto_relogin_if_needed(self, username: str) -> bool:
            state = self.accounts.get(username)

            if not state:
                return False

            # Уже идёт перелогин другим вызовом
            if state.relogin_in_progress:
                self.logger.info(
                    f"Перелогин для {username} уже выполняется, ждём результат",
                    username
                )

                for _ in range(30):
                    await asyncio.sleep(1)

                    if not state.relogin_in_progress:
                        updated_state = self.accounts.get(username)
                        return bool(updated_state and not updated_state.need_relogin)

                return False

            # Проверяем, действительно ли нужен перелогин
            needs_relogin = state.need_relogin

            if not needs_relogin and state.browser:
                try:
                    needs_relogin = await self._is_on_login_page(state.browser)
                except Exception:
                    needs_relogin = False

            if not needs_relogin:
                return True

            state.relogin_in_progress = True

            try:
                self.logger.info(
                    f"Начинаем автоматический перелогин для {username}",
                    username
                )

                # Закрываем старый браузер
                if state.browser:
                    try:
                        state.browser.quit()
                    except Exception:
                        pass

                    state.browser = None

                accounts = self.load_accounts()

                account_data = next(
                    (
                        acc for acc in accounts
                        if acc.get("username") == username
                    ),
                    None
                )

                if not account_data:
                    self.logger.error(
                        f"Не найдены данные аккаунта для {username}",
                        username
                    )
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

                await self.login_account(credentials)

                # Достаем СВЕЖИЙ state из словаря self.accounts
                new_state = self.accounts.get(username)

                if not new_state or not new_state.browser:
                    raise Exception("После перелогина браузер или state отсутствует")

                if not await self._is_logged_in(new_state.browser):
                    raise Exception("После перелогина аккаунт всё ещё не авторизован")

                new_state.need_relogin = False
                new_state.status_reason = ""

                self.logger.info(
                    f"Автоматический перелогин успешен для {username}",
                    username
                )

                return True

            except Exception as e:
                curr_state = self.accounts.get(username, state)
                curr_state.need_relogin = True
                curr_state.status_reason = "RELOGIN FAILED"

                self.logger.error(
                    f"Автоматический перелогин не удался для {username}: {e}",
                    username
                )

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

    async def _is_logged_in(self, browser: webdriver.Chrome) -> bool:
        """Обновленный метод для совместимости с остальным кодом"""
        status = await self._check_auth_state(browser)
        return status == AuthStatus.OK

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

class TwitterOperations:
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
                    self.logger.info("Cookies accepted")
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
                    self.logger.info("Cookies accepted via CSS selector")
                    await asyncio.sleep(0.5)
                    return
                except:
                    continue

        except Exception as e:
            self.logger.debug(f"Cookie acceptance failed or not needed: {e}")

    async def find_groups(self, browser, username: str) -> set:
        """
        Открывает iChat и собирает все доступные ссылки /i/chat/<id>.
        Список прокручивается постепенно, чтобы X успевал подгружать
        дополнительные группы.
        """

        groups = set()

        if not browser:
            print(f"[{username}] FIND GROUPS: browser отсутствует")
            return groups

        loop = asyncio.get_event_loop()

        try:
            print(f"\n===== FIND GROUPS START: {username} =====")
            print(f"[{username}] BEFORE URL: {browser.current_url}")
            print(f"[{username}] BEFORE TITLE: {browser.title}")

            # ---------------------------------------------------------
            # 1. Открываем iChat
            # ---------------------------------------------------------

            self.logger.info(
                "Открываем iChat для сбора групп...",
                username
            )

            await loop.run_in_executor(
                None,
                lambda: browser.get("https://x.com/i/chat")
            )

            await asyncio.sleep(random.uniform(3, 5))
            await self._accept_cookies(browser)

            self.logger.info(
                f"[{username}] iChat URL после перехода: {browser.current_url}",
                username
            )

            await asyncio.sleep(1)

            print(f"[{username}] AFTER URL: {browser.current_url}")
            print(f"[{username}] AFTER TITLE: {browser.title}")

            # ---------------------------------------------------------
            # 2. Собираем группы + прокручиваем список
            # ---------------------------------------------------------

            max_scrolls = 30
            no_new_rounds = 0

            for scroll_num in range(max_scrolls):

                # -----------------------------------------------------
                # Получаем все текущие ссылки
                # -----------------------------------------------------

                anchors = await loop.run_in_executor(
                    None,
                    lambda: browser.find_elements(
                        By.CSS_SELECTOR,
                        "a[href*='/i/chat/']"
                    )
                )

                before_count = len(groups)

                # -----------------------------------------------------
                # Добавляем найденные группы
                # -----------------------------------------------------

                for anchor in anchors:
                    try:
                        href = await loop.run_in_executor(
                            None,
                            lambda a=anchor: a.get_attribute("href")
                        )

                        if not href:
                            continue

                        href = href.split("?", 1)[0].rstrip("/")

                        match = re.search(
                            r"https?://(?:www\.)?x\.com/i/chat/([^/?#]+)",
                            href
                        )

                        if not match:
                            continue

                        chat_id = match.group(1)

                        if not chat_id:
                            continue

                        # Берём только групповые чаты.
                        # Группа: g2035650823573876754
                        # Личный чат: 110805057-1123456508
                        if not chat_id.startswith("g"):
                            continue

                        normalized_url = (
                            f"https://x.com/i/chat/{chat_id}"
                        )

                        if normalized_url not in groups:
                            groups.add(normalized_url)

                            print(
                                f"[{username}] FOUND GROUP: "
                                f"{normalized_url}"
                            )

                    except Exception:
                        continue

                # -----------------------------------------------------
                # Проверяем, появились ли новые группы
                # -----------------------------------------------------

                current_count = len(groups)

                self.logger.info(
                    f"[{username}] Парсинг: "
                    f"шаг {scroll_num + 1}/{max_scrolls}, "
                    f"найдено групп: {current_count}",
                    username
                )

                if current_count > before_count:
                    no_new_rounds = 0
                else:
                    no_new_rounds += 1

                # -----------------------------------------------------
                # Прокручиваем наиболее вероятный scroll-контейнер
                # -----------------------------------------------------

                await loop.run_in_executor(
                    None,
                    lambda: browser.execute_script("""
                        const elements = document.querySelectorAll('*');

                        let best = null;
                        let bestScore = 0;

                        for (const el of elements) {
                            try {
                                const style = getComputedStyle(el);

                                const scrollable =
                                    style.overflowY === 'auto' ||
                                    style.overflowY === 'scroll';

                                if (!scrollable) {
                                    continue;
                                }

                                const scrollableHeight =
                                    el.scrollHeight - el.clientHeight;

                                if (scrollableHeight <= 100) {
                                    continue;
                                }

                                const score =
                                    scrollableHeight + el.clientHeight;

                                if (score > bestScore) {
                                    best = el;
                                    bestScore = score;
                                }

                            } catch (e) {}
                        }

                        if (best) {
                            best.scrollTop += Math.max(
                                500,
                                best.clientHeight * 0.8
                            );

                            return {
                                found: true,
                                scrollTop: best.scrollTop,
                                scrollHeight: best.scrollHeight,
                                clientHeight: best.clientHeight
                            };
                        }

                        window.scrollBy(
                            0,
                            Math.max(500, window.innerHeight * 0.8)
                        );

                        return {
                            found: false,
                            scrollTop: window.scrollY,
                            scrollHeight: document.body.scrollHeight,
                            clientHeight: window.innerHeight
                        };
                    """)
                )

                # Даём X время подгрузить следующую порцию
                await asyncio.sleep(1.0)

                # -----------------------------------------------------
                # Если несколько проходов подряд нет новых групп,
                # вероятно, дошли до конца списка
                # -----------------------------------------------------

                if no_new_rounds >= 4:
                    self.logger.info(
                        f"[{username}] Новых групп несколько проходов нет. "
                        f"Заканчиваем парсинг.",
                        username
                    )
                    break

            # ---------------------------------------------------------
            # 3. Финальный проход по DOM
            # ---------------------------------------------------------

            anchors = await loop.run_in_executor(
                None,
                lambda: browser.find_elements(
                    By.CSS_SELECTOR,
                    "a[href*='/i/chat/']"
                )
            )

            for anchor in anchors:
                try:
                    href = await loop.run_in_executor(
                        None,
                        lambda a=anchor: a.get_attribute("href")
                    )

                    if not href:
                        continue

                    href = href.split("?", 1)[0].rstrip("/")

                    match = re.search(
                        r"https?://(?:www\.)?x\.com/i/chat/([^/?#]+)",
                        href
                    )

                    if match:
                        chat_id = match.group(1)

                        if chat_id and chat_id.startswith("g"):
                            groups.add(
                                f"https://x.com/i/chat/{chat_id}"
                            )

                except Exception:
                    continue

            # ---------------------------------------------------------
            # 4. Итог
            # ---------------------------------------------------------

            print(
                f"[{username}] "
                f"===== GROUPS FOUND: {len(groups)} ====="
            )

            for group_url in sorted(groups):
                print(
                    f"[{username}] GROUP: {group_url}"
                )

            self.logger.info(
                f"Сбор iChat завершен. "
                f"Найдено ссылок: {len(groups)}",
                username
            )

            return groups

        except Exception as e:

            print(
                f"[{username}] FIND GROUPS ERROR: {e}"
            )

            self.logger.error(
                f"Ошибка сбора iChat-групп: {e}",
                username
            )

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
    # -------------------------------------------------
    async def _fill_message_reliably(self, browser, message_box, text):
        """
        Надёжно заполняет поле текстом.
        Сообщение НЕ отправляет.
        """

        loop = asyncio.get_running_loop()

        def fill():
            try:
                message_box.click()
            except Exception:
                browser.execute_script(
                    "arguments[0].focus();",
                    message_box
                )

            tag = message_box.tag_name.lower()

            if tag == "textarea":
                current_value = browser.execute_script(
                    """
                    const el = arguments[0];

                    const setter =
                        Object.getOwnPropertyDescriptor(
                            HTMLTextAreaElement.prototype,
                            'value'
                        ).set;

                    setter.call(el, '');

                    el.dispatchEvent(
                        new Event('input', {bubbles: true})
                    );
                    
                    """,
                    message_box
                )

                if current_value:
                    raise RuntimeError(
                        f"Не удалось очистить поле ввода: осталось {len(current_value)} символов"
                    )

            with CLIPBOARD_LOCK:
                pyperclip.copy(text)

                message_box.send_keys(
                    Keys.CONTROL,
                    "v"
                )

        await loop.run_in_executor(None, fill)

        await asyncio.sleep(1)

        actual = await loop.run_in_executor(
            None,
            lambda: browser.execute_script(
                """
                const el = arguments[0];
                return 'value' in el ? el.value : el.innerText;
                """,
                message_box
            )
        )

        if actual != text:
            self.logger.warning(
                f"Текст в поле отличается: "
                f"ожидалось {len(text)} символов, "
                f"получено {len(actual or '')}"
            )
            return False

        return True
    
    async def _simulate_typing(self, account_state, message_box, message: str):
        if not account_state or not account_state.humanizer:
            return
        try:
            loop = asyncio.get_event_loop()
            await self.check_pause(account_state)
            active = await loop.run_in_executor(None, lambda: account_state.browser.execute_script(
                "return document.activeElement === arguments[0]", message_box))
            if not active:
                await loop.run_in_executor(None, lambda: account_state.browser.execute_script("arguments[0].click();", message_box))
                await asyncio.sleep(1)
            await loop.run_in_executor(None, lambda: account_state.browser.execute_script("arguments[0].innerHTML = '';", message_box))
            await loop.run_in_executor(None, account_state.humanizer.simulate_typing, message_box, message, self.logger)
        except Exception as e:
            self.logger.error(f"Ошибка в симуляции набора: {str(e)}", account_state.username)
            raise

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
            



    async def _send_message_button(self, browser, username: str) -> bool:
        """
        Отправляет сообщение в iChat / DM X.

        Порядок:
        1. Ищем кнопку Send.
        2. Проверяем, что она не disabled.
        3. Обычный click.
        4. Если не получилось — JS click.
        5. Если не получилось — Enter в textarea.
        6. После каждой попытки проверяем, что отправка произошла.
        """

        loop = asyncio.get_event_loop()

        send_btn_xpath = (
            "//button[@data-testid='dmComposerSendButton'] | "
            "//div[@data-testid='dmComposerSendButton'] | "
            "//button[@aria-label='Send' or @aria-label='Отправить'] | "
            "//div[@role='button'][@aria-label='Send' or @aria-label='Отправить']"
        )

        textarea_xpath = (
            "//textarea[@data-testid='dm-composer-textarea'] | "
            "//textarea[@placeholder='Message'] | "
            "//textarea[@aria-label='Message']"
        )

        # ------------------------------------------------------------
        # Проверка, что сообщение действительно отправилось
        # ------------------------------------------------------------

        async def verify_sent():
            """
            После отправки ждём немного и проверяем textarea.

            Если textarea исчезла или стала пустой — считаем,
            что React/X обработал отправку.
            """

            for _ in range(8):
                await asyncio.sleep(0.5)

                try:
                    boxes = browser.find_elements(
                        By.XPATH,
                        textarea_xpath
                    )

                    if not boxes:
                        self.logger.info(
                            "✅ После отправки textarea исчезла.",
                            username
                        )
                        return True

                    box = boxes[0]

                    value = (
                        box.get_attribute("value")
                        or box.get_attribute("textContent")
                        or ""
                    )

                    if not value.strip():
                        self.logger.info(
                            "✅ После отправки textarea стала пустой.",
                            username
                        )
                        return True

                except Exception as e:
                    self.logger.warning(
                        f"Ошибка проверки результата отправки: "
                        f"{type(e).__name__}: {e}",
                        username
                    )

            self.logger.warning(
                "⚠️ Не удалось подтвердить факт отправки сообщения.",
                username
            )

            return False

        # ------------------------------------------------------------
        # 1. Находим кнопку и проверяем её состояние
        # ------------------------------------------------------------

        def get_send_button():
            try:
                btn = WebDriverWait(browser, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, send_btn_xpath)
                    )
                )

                return btn

            except Exception as e:
                self.logger.warning(
                    f"❌ Кнопка Send не найдена: "
                    f"{type(e).__name__}: {e}",
                    username
                )
                return None

        btn = await loop.run_in_executor(
            None,
            get_send_button
        )

        if btn is None:
            self.logger.warning(
                "❌ Кнопка отправки отсутствует.",
                username
            )
        else:
            try:
                disabled = btn.get_attribute("disabled")
                aria_disabled = btn.get_attribute("aria-disabled")

                self.logger.info(
                    f"Кнопка Send найдена. "
                    f"disabled={disabled}, "
                    f"aria-disabled={aria_disabled}",
                    username
                )

                if disabled is not None or aria_disabled == "true":
                    self.logger.warning(
                        "⚠️ Кнопка Send найдена, но она отключена.",
                        username
                    )

            except Exception as e:
                self.logger.warning(
                    f"Не удалось проверить состояние кнопки: "
                    f"{type(e).__name__}: {e}",
                    username
                )

        # ------------------------------------------------------------
        # 2. Обычный click
        # ------------------------------------------------------------

        def click_send_btn():
            try:
                btn = WebDriverWait(browser, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, send_btn_xpath)
                    )
                )

                self.logger.info(
                    "Пробуем обычный click по кнопке Send.",
                    username
                )

                btn.click()

                return True

            except Exception as e:
                self.logger.warning(
                    f"❌ Обычный click не сработал: "
                    f"{type(e).__name__}: {e}",
                    username
                )
                return False

        clicked = await loop.run_in_executor(
            None,
            click_send_btn
        )

        if clicked:
            self.logger.info(
                "Клик по Send выполнен. Проверяем отправку...",
                username
            )

            if await verify_sent():
                self.logger.info(
                    "✅ Сообщение подтверждённо отправлено обычным click.",
                    username
                )
                return True

            self.logger.warning(
                "⚠️ Клик прошёл, но отправка не подтверждена.",
                username
            )

        # ------------------------------------------------------------
        # 3. JS click
        # ------------------------------------------------------------

        def js_click_send_btn():
            try:
                btn = browser.find_element(
                    By.XPATH,
                    send_btn_xpath
                )

                self.logger.info(
                    "Пробуем JS click по кнопке Send.",
                    username
                )

                browser.execute_script(
                    "arguments[0].click();",
                    btn
                )

                return True

            except Exception as e:
                self.logger.warning(
                    f"❌ JS click не сработал: "
                    f"{type(e).__name__}: {e}",
                    username
                )
                return False

        clicked_js = await loop.run_in_executor(
            None,
            js_click_send_btn
        )

        if clicked_js:
            self.logger.info(
                "JS click выполнен. Проверяем отправку...",
                username
            )

            if await verify_sent():
                self.logger.info(
                    "✅ Сообщение подтверждённо отправлено через JS.",
                    username
                )
                return True

            self.logger.warning(
                "⚠️ JS click выполнен, но отправка не подтверждена.",
                username
            )

        # ------------------------------------------------------------
        # 4. Enter
        # ------------------------------------------------------------

        def send_enter_key():
            try:
                box = browser.find_element(
                    By.XPATH,
                    textarea_xpath
                )

                self.logger.info(
                    "Пробуем отправить сообщение через Enter.",
                    username
                )

                box.click()
                box.send_keys(Keys.RETURN)

                return True

            except Exception as e:
                self.logger.warning(
                    f"❌ Enter не сработал: "
                    f"{type(e).__name__}: {e}",
                    username
                )
                return False

        enter_sent = await loop.run_in_executor(
            None,
            send_enter_key
        )

        if enter_sent:
            self.logger.info(
                "Enter выполнен. Проверяем отправку...",
                username
            )

            if await verify_sent():
                self.logger.info(
                    "✅ Сообщение подтверждённо отправлено через Enter.",
                    username
                )
                return True

            self.logger.warning(
                "⚠️ Enter выполнен, но отправка не подтверждена.",
                username
            )

        # ------------------------------------------------------------
        # Все способы провалились
        # ------------------------------------------------------------

        self.logger.error(
            "❌ Не удалось подтвердить отправку: "
            "обычный click, JS click и Enter не дали подтверждённого результата.",
            username
        )

        return False


    async def send_message(self, state: AccountState, group_url: str, message_text: str, humanize: bool = True) -> str:
        """
        Отправляет сообщение в указанную группу iChat.
        Возвращает один из статусов: "SUCCESS", "FAILED", "BROWSER_CLOSED", "NEED_RELOGIN", "PAGE_DOWN", "LIMIT_REACHED", "DRY_RUN".
        """
        browser = state.browser
        username = state.username

        if not browser:
            self.logger.warning("Браузер не передан или закрыт.", username)
            return "BROWSER_CLOSED"

        try:
            browser.get(group_url)
            await asyncio.sleep(random.uniform(3, 5))

            # 1. Проверяем, жив ли браузер
            try:
                if (
                    not browser
                    or not getattr(browser, "service", None)
                    or not browser.service.is_connectable()
                ):
                    return "BROWSER_CLOSED"
            except Exception:
                return "BROWSER_CLOSED"

            # 2. Проверяем состояние страницы
            try:
                current_url = browser.current_url.lower()
                page_source = browser.page_source.lower()

                if "/login" in current_url or "/i/flow/login" in current_url:
                    self.logger.warning("Обнаружена страница входа.", username)
                    return "NEED_RELOGIN"

                if (
                    "this page is down" in page_source
                    or "something went wrong" in page_source
                    or "try reloading" in page_source
                ):
                    self.logger.warning(f"Страница X недоступна (Page Down): {group_url}", username)
                    return "PAGE_DOWN"

            except Exception as e:
                self.logger.error(f"Ошибка проверки состояния страницы: {str(e)}", username)
                return "FAILED"

            # 3. Ищем поле ввода (textarea) по обновленному селектору из DevTools
            input_xpath = (
                "//textarea[@data-testid='dm-composer-textarea'] | "
                "//textarea[@placeholder='Message' or @aria-label='Message'] | "
                "//textarea[contains(@placeholder, 'message')] | "
                "//textarea"
            )

            try:
                input_box = WebDriverWait(browser, 10).until(
                    EC.presence_of_element_located((By.XPATH, input_xpath))
                )
            except Exception:
                self.logger.warning(f"Не найдено поле ввода (textarea) в {group_url}", username)
                return "FAILED"

            # Фокусировка и клик по полю
            try:
                browser.execute_script("arguments[0].focus(); arguments[0].click();", input_box)
            except Exception:
                input_box.click()

            await asyncio.sleep(0.5)

            # Очищаем поле через выделение (clear() иногда не стриггеривает React state)
            try:
                input_box.send_keys(Keys.CONTROL + "a")
                input_box.send_keys(Keys.BACKSPACE)
            except Exception:
                pass

            # Ввод текста
            if humanize:
                for char in message_text:
                    if char == '\n':
                        input_box.send_keys(Keys.SHIFT, Keys.ENTER)
                    else:
                        input_box.send_keys(char)
                    await asyncio.sleep(random.uniform(0.02, 0.06))
            else:
                # Для не-humanize режима посылаем полноценные эвенты 'input' и 'change', чтобы React разблокировал кнопку Send
                browser.execute_script(
                    """
                    var el = arguments[0];
                    var text = arguments[1];
                    el.value = text;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    input_box,
                    message_text
                )

            await asyncio.sleep(1)

            # 4. Вызываем подготовленный метод отправки сообщения
            sent = await self._send_message_button(browser, username)
            if sent:
                await asyncio.sleep(random.uniform(2, 4))
                return "SUCCESS"
            else:
                return "FAILED"

        except Exception as e:
            err_msg = str(e)
            if "Target page, context or browser has been closed" in err_msg or "webSocketWithURL" in err_msg:
                return "BROWSER_CLOSED"

            self.logger.error(f"Ошибка при отправке сообщения в {group_url}: {err_msg}", username)
            return "FAILED"

class MessageManager:
        def __init__(self, config: Config, logger: Logger):
            self.config = config
            self.logger = logger
            self.account_messages: Dict[str, List[Dict[str, Any]]] = {}
            self.load_messages()

        def load_messages(self) -> None:
            try:
                if self.config.account_messages_file.exists():
                    with open(self.config.account_messages_file, 'r', encoding='utf-8') as f:
                        self.account_messages = json.load(f)
            except Exception as e:
                self.logger.error(f"Ошибка загрузки сообщений: {e}")
                self.account_messages = {}

        def save_account_messages(self):
            try:
                with open(self.config.account_messages_file, 'w', encoding='utf-8') as f:
                    json.dump(self.account_messages, f, ensure_ascii=False, indent=4)
                self.logger.info("Все сообщения аккаунтов сохранены успешно")
            except Exception as e:
                self.logger.error(f"Ошибка сохранения сообщений аккаунтов: {e}")

        def save_messages(self, username: str, messages: List[Dict[str, Any]]) -> None:
            try:
                self.account_messages[username] = messages
                self.save_account_messages()
                self.logger.info("Список сообщений сохранен успешно", username)
            except Exception as e:
                self.logger.error(f"Ошибка сохранения сообщений: {e}", username)

        def get_messages(self, username: str) -> List[Dict[str, Any]]:
            messages_data = self.account_messages.get(username, [])
            if not messages_data:
                return []
            
            if isinstance(messages_data, str):
                self.logger.warning(f"Обнаружен старый формат сообщений (строка) для {username}. Конвертируем.", username)
                return [{"text": messages_data, "count": 1}]

            if isinstance(messages_data, list) and all(isinstance(item, str) for item in messages_data):
                self.logger.warning(f"Обнаружен старый формат сообщений (список строк) для {username}. Конвертируем.", username)
                return [{"text": msg, "count": 1} for msg in messages_data]

            if isinstance(messages_data, list) and all(isinstance(item, dict) for item in messages_data):
                valid_data = []
                for item in messages_data:
                    if "text" in item and "count" in item:
                        valid_data.append(item)
                return valid_data
                
            self.logger.error(f"Неизвестный формат сообщений для {username}. Пожалуйста, проверьте account_messages.json.", username)
            return []

class CycleManager:
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger

    def get_cycle_settings(self, username: str) -> CycleSettings:
        try:
            if self.config.cycle_settings_file.exists():
                with open(self.config.cycle_settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    user_settings = data.get(username, {})
                    return CycleSettings(
                        messages_per_cycle=int(user_settings.get("messages_per_cycle", 50)),
                        rest_time_minutes=int(user_settings.get("rest_time_minutes", 30)),
                        retweet_count=int(user_settings.get("retweet_count", 1)),
                        max_total_retweets=int(user_settings.get("max_total_retweets", 50)),
                        media_enabled=bool(user_settings.get("media_enabled", False))
                    )
        except Exception as e:
            self.logger.error(f"Ошибка загрузки настроек цикла для {username}: {e}")
        return CycleSettings()

    def save_cycle_settings(self, username: str, settings: CycleSettings) -> None:
        try:
            data = {}
            if self.config.cycle_settings_file.exists():
                with open(self.config.cycle_settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data[username] = {
                "messages_per_cycle": settings.messages_per_cycle,
                "rest_time_minutes": settings.rest_time_minutes,
                "retweet_count": settings.retweet_count,
                "max_total_retweets": settings.max_total_retweets,
                "media_enabled": settings.media_enabled
            }
            with open(self.config.cycle_settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            self.logger.info(f"Настройки цикла обновлены для {username}")
        except Exception as e:
            self.logger.error(f"Ошибка сохранения настроек цикла для {username}: {e}")

class CommentManager:
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
    
    def get_comment_settings(self, username: str) -> CommentSettings:
        try:
            if self.config.comment_settings_file.exists():
                with open(self.config.comment_settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    s = data.get(username, {})
                    return CommentSettings(
                        enabled=bool(s.get("enabled", False)),
                        targets_file=s.get("targets_file", ""),
                        comments_file=s.get("comments_file", ""),
                        photo_path=s.get("photo_path", ""),
                        daily_limit=int(s.get("daily_limit", 0))
                    )
        except Exception as e:
            self.logger.error(f"Ошибка загрузки настроек комментариев для {username}: {e}")
        return CommentSettings()

    def save_comment_settings(self, username: str, settings: CommentSettings) -> None:
        try:
            data = {}
            if self.config.comment_settings_file.exists():
                with open(self.config.comment_settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data[username] = {
                "enabled": settings.enabled,
                "targets_file": settings.targets_file,
                "comments_file": settings.comments_file,
                "photo_path": settings.photo_path,
                "daily_limit": settings.daily_limit
            }
            with open(self.config.comment_settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            self.logger.info(f"Настройки комментариев обновлены для {username}")
        except Exception as e:
            self.logger.error(f"Ошибка сохранения настроек комментариев для {username}: {e}")

class TaskScheduler:
    def __init__(self, logger: Logger, gui_update_callback: Callable, account_manager: AccountManager):
        self.logger = logger
        self.running_tasks = {}
        self.tasks_lock = threading.Lock()  # Lock for thread-safe access to running_tasks
        self.gui_update_callback = gui_update_callback
        self.account_manager = account_manager
        self.telegram_bot_manager = None

    def _chat_store_paths(self):
        return Path("chat_cache.json"), Path("chat_queue.json")

    def _load_chat_store(self, username: str):
        cache_file, queue_file = self._chat_store_paths()

        cache_data = {}
        queue_data = {}

    # ---------- CACHE ----------
        try:
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)

                if isinstance(raw, dict):
                    cache_data = raw

        except Exception as e:
            self.logger.warning(
                f"[{username}] Не удалось прочитать chat_cache.json: {e}",
                username
            )

        # ---------- QUEUE ----------
        try:
            if queue_file.exists():
                with open(queue_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)

                if isinstance(raw, dict):
                    queue_data = raw

        except Exception as e:
            self.logger.warning(
                f"[{username}] Не удалось прочитать chat_queue.json: {e}",
                username
            )

        cache = cache_data.get(username, [])
        queue = queue_data.get(username, [])

        if not isinstance(cache, list):
            cache = []

        if not isinstance(queue, list):
            queue = []

    # Убираем дубли и пустые значения
        cache = list(dict.fromkeys(
            str(x).strip()
            for x in cache
            if x
        ))

        queue = list(dict.fromkeys(
            str(x).strip()
            for x in queue
            if x
        ))

        return cache, queue

    def _save_chat_store(self, username: str, cache: list, queue: list):
        cache_file, queue_file = self._chat_store_paths()

        cache_all = {}
        queue_all = {}

        try:
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        cache_all = raw
        except Exception:
            pass

        try:
            if queue_file.exists():
                with open(queue_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        queue_all = raw
        except Exception:
            pass

        cache_all[username] = list(dict.fromkeys(cache))
        queue_all[username] = list(dict.fromkeys(queue))

        tmp_cache = cache_file.with_suffix(".tmp")
        tmp_queue = queue_file.with_suffix(".tmp")

        with open(tmp_cache, "w", encoding="utf-8") as f:
            json.dump(cache_all, f, ensure_ascii=False, indent=4)
        with open(tmp_queue, "w", encoding="utf-8") as f:
            json.dump(queue_all, f, ensure_ascii=False, indent=4)

        tmp_cache.replace(cache_file)
        tmp_queue.replace(queue_file)

    async def _refresh_ichat_groups(self, account_state, twitter_ops):
        username = account_state.username

        self.logger.info(
            f"[{username}] Начинаем сбор групп непосредственно из iChat...",
            username
        )

        groups = await twitter_ops.find_groups(account_state.browser, username)
        groups = sorted(set(groups))

        if not groups:
            self.logger.warning(
                f"[{username}] iChat не вернул ни одной прямой ссылки.",
                username
            )
            return []

        old_cache, old_queue = self._load_chat_store(username)
        old_cache_set = set(old_cache)

        # Кеш содержит актуальные найденные ссылки.
        new_cache = groups
        new_cache_set = set(new_cache)

        # Сохраняем непройденные ссылки из старой очереди.
        queue = [g for g in old_queue if g in new_cache_set]

        # Новые ссылки добавляем в очередь.
        for group in new_cache:
            if group not in old_cache_set and group not in queue:
                queue.append(group)

        # Если очередь исчерпана, начинаем новый полный проход в случайном порядке.
        if not queue:
            queue = new_cache.copy()
            random.shuffle(queue)

        self._save_chat_store(username, new_cache, queue)

        account_state.groups = set(new_cache)
        self.account_manager.save_groups()

        self.logger.info(
            f"[{username}] 📦 Сохранено iChat-групп: {len(new_cache)}; "
            f"в очереди осталось: {len(queue)}",
            username
        )
        return new_cache

    def _get_next_chat(self, username: str, available_groups):
        cache, queue = self._load_chat_store(username)
        available = set(available_groups)

        self.logger.info(
            f"[{username}] CHAT STORE DEBUG: "
            f"available={len(available)}, "
            f"cache={len(cache)}, "
            f"queue={len(queue)}",
            username
    )

        if not cache:
            cache = sorted(available)

        queue = [g for g in queue if g in available]

        if not queue:
            queue = [g for g in cache if g in available]
            random.shuffle(queue)

        if not queue:
            self.logger.warning(
                f"[{username}] CHAT STORE: очередь пуста после фильтрации",
                username
            )
            return None

        selected = queue.pop(0)

        self._save_chat_store(username, cache, queue)

        self.logger.info(
            f"[{username}] 🎯 Выбрана iChat-группа: {selected} "
            f"(осталось в очереди: {len(queue)})",
            username
        )

        return selected

    def _return_chat_to_queue(self, username: str, group_link: str):
        cache, queue = self._load_chat_store(username)
        if group_link in cache and group_link not in queue:
            queue.append(group_link)
            self._save_chat_store(username, cache, queue)

    async def start_sending_cycle(self, account_state: AccountState, twitter_ops: TwitterOperations, account_manager: AccountManager, humanize: bool = True):
            try:
                # Обновляем временные сообщения из БД перед началом рассылки
                if self.telegram_bot_manager:
                    self.telegram_bot_manager.refresh_temp_messages_from_db()

                # Перед рассылкой автоматически собираем актуальные ссылки прямо из iChat.
                fresh_groups = await self._refresh_ichat_groups(account_state, twitter_ops)
                if not fresh_groups:
                    self.logger.error(
                        "Нет доступных iChat-групп. Останавливаем цикл.",
                        account_state.username
                    )
                    return

                # Обычные сообщения
                messages_to_send = list(account_state.mailing_messages)
                if not messages_to_send:
                    self.logger.error("Список сообщений для рассылки пуст. Останавливаем цикл.", account_state.username)
                    return

                cycle_messages_limit = account_state.cycle_settings.messages_per_cycle
                rest_time_seconds = account_state.cycle_settings.rest_time_minutes * 60

                self.logger.info(f"Начинаем цикл отправки для {account_state.username}.", account_state.username)

                while account_state.is_active:
                    # Обновляем спец-сообщения из БД перед новым циклом
                    spec_count = 0
                    spec_msgs = []
                    if self.telegram_bot_manager:
                        self.telegram_bot_manager.refresh_temp_messages_from_db()
                        tm = self.telegram_bot_manager.temp_messages
                        tm["sent_this_cycle"] = False
                        spec_msgs = tm.get("messages", [])
                        spec_count = len(spec_msgs)

                    # Инициализация счетчиков спец-сообщений для текущего цикла аккаунта
                    account_state.spec_sent_count = 0
                    account_state.spec_total_remaining = spec_count
                    account_state.spec_random_pos = random.randint(3, max(3, int(cycle_messages_limit * 0.8)))
                    
                    messages_sent_this_cycle = 0

                    while messages_sent_this_cycle < cycle_messages_limit:
                        if not account_state.is_active:
                            break

                        # Проверка состояния браузера
                        try:
                            browser_alive = await account_manager.check_browser_health(account_state.browser)
                            if not browser_alive:
                                self.logger.warning("Browser session closed manually. Setting account to inactive.", account_state.username)
                                account_state.is_active = False
                                account_state.browser = None
                                account_state.status_reason = "BROWSER_CLOSED"
                                self.gui_update_callback()
                                break
                        except Exception as e:
                            self.logger.warning(f"Browser health check failed with exception: {e}. Setting account to inactive.", account_state.username)
                            account_state.is_active = False
                            account_state.browser = None
                            account_state.status_reason = "BROWSER_CLOSED"
                            self.gui_update_callback()
                            break

                        while account_state.is_paused:
                            await asyncio.sleep(2)
                        
                        # --- ПРОВЕРКА НА ПЕРЕЛОГИН ПЕРЕД ОТПРАВКОЙ ---
                        if account_state.need_relogin:
                            username = account_state.username
                            self.logger.info("Аккаунту нужен перелогин. Проверяем возможность автоматического перелогина...", username)

                            success = await account_manager.auto_relogin_if_needed(username)
                            if not success:
                                self.logger.warning("Автоматический перелогин не удался. Ожидаем перед следующей попыткой...", username)
                                await asyncio.sleep(60)
                                continue

                            account_state = account_manager.accounts.get(username)
                            if not account_state or not account_state.browser:
                                self.logger.error("После перелогина браузер аккаунта недоступен. Останавливаем цикл.", username)
                                return

                            self.logger.info("Автоматический перелогин завершён. Продолжаем отправку.", username)

                        if account_state.message_index >= len(messages_to_send):
                            account_state.message_index = 0
                            account_state.message_sent_count = 0

                        current_message_obj = messages_to_send[account_state.message_index]
                        current_message_text = current_message_obj.get("text", "")
                        required_send_count = int(current_message_obj.get("count", 1))

                        if not current_message_text:
                            account_state.message_index = (account_state.message_index + 1) % len(messages_to_send)
                            account_state.message_sent_count = 0
                            continue
                        
                        current_group = self._get_next_chat(account_state.username, fresh_groups)
                        if not current_group:
                            self.logger.error("Очередь iChat-групп пуста. Останавливаем цикл.", account_state.username)
                            break

                        wait_time = random.uniform(15, 30)
                        self.logger.info(f"Отправляем в {current_group} (ждем {wait_time:.1f}с)...", account_state.username)
                        await asyncio.sleep(wait_time)

                        status = await twitter_ops.send_message(
                            state=account_state,
                            group_url=current_group,
                            message_text=current_message_text,
                            humanize=humanize
                        )

                        if status == "DRY_RUN":
                            self.logger.info(f"[{account_state.username}] 🧪 DRY-RUN завершен: {current_group}. Отправка отключена.", account_state.username)
                            return

                        if status == "BROWSER_CLOSED":
                            self.logger.warning("Browser closed during message sending. Setting account to inactive.", account_state.username)
                            account_state.is_active = False
                            account_state.browser = None
                            account_state.status_reason = "BROWSER_CLOSED"
                            self.gui_update_callback()
                            break

                        elif status == "NEED_RELOGIN":
                            self.logger.warning("Аккаунту нужен перелогин. Устанавливаем флаг...", account_state.username)
                            account_state.need_relogin = True
                            account_state.status_reason = "RELOGIN"
                            self.gui_update_callback()
                            continue    
                        
                        elif status == "FAILED":
                            self.logger.warning(
                                f"❌ Не удалось отправить сообщение в {current_group}. "
                                f"Группу НЕ удаляем — повторим позже.",
                                account_state.username
                            )

                            await asyncio.sleep(random.uniform(4, 8))
                            continue
                        elif status == "LIMIT_REACHED":
                            self.logger.warning("🛑 ДОСТИГНУТ ЛИМИТ DM! Ставим аккаунт на паузу на 4 часа...", account_state.username)
                            account_state.status_reason = "DM LIMIT 4H"
                            self.gui_update_callback()
                            await asyncio.sleep(14400)
                            account_state.status_reason = ""
                            continue

                        elif status == "SUCCESS":
                            account_state.messages_sent += 1
                            account_state.message_sent_count += 1
                            messages_sent_this_cycle += 1

                            # --- Логика отправки спец-сообщений ---
                            should_send_spec = False
                            if spec_count == 1 and account_state.spec_sent_count == 0 and account_state.spec_total_remaining > 0:
                                if messages_sent_this_cycle >= account_state.spec_random_pos:
                                    should_send_spec = True
                            elif spec_count >= 2 and account_state.spec_total_remaining > 0:
                                if messages_sent_this_cycle % 5 == 0 and account_state.spec_sent_count < spec_count:
                                    should_send_spec = True

                            if spec_msgs and should_send_spec:
                                idx_to_send = account_state.spec_sent_count % spec_count
                                temp_msg = spec_msgs[idx_to_send]
                                special_group = random.choice(fresh_groups)
                                
                                wait_time_temp = random.uniform(15, 30)
                                self.logger.info(f"Отправляем СПЕЦ СООБЩЕНИЕ в {special_group} (ждем {wait_time_temp:.1f}с)...", account_state.username)
                                await asyncio.sleep(wait_time_temp)

                                status_temp = await twitter_ops.send_message(
                                    state=account_state,
                                    group_url=special_group,
                                    message_text=temp_msg,
                                    humanize=True
                                )

                                if status_temp == "SUCCESS":
                                    pc_id = getattr(self.telegram_bot_manager.config, 'pc_id', 'PC_UNKNOWN') if self.telegram_bot_manager else "PC_UNKNOWN"
                                    notification = f"[{pc_id}] Аккаунт @{account_state.username} отправил спец сообщение в {special_group}"
                                    try:
                                        if self.telegram_bot_manager:
                                            await self.telegram_bot_manager.bot.send_message(
                                                chat_id=self.telegram_bot_manager.config.chat_id, 
                                                text=notification
                                            )
                                    except Exception as e:
                                        self.logger.error(f"Failed to send notification: {e}", account_state.username)
                                else:
                                    self.logger.warning(f"Failed to send special message: {status_temp}", account_state.username)

                                account_state.spec_sent_count += 1
                                account_state.spec_total_remaining -= 1

                        if account_state.message_sent_count >= required_send_count:
                            account_state.message_index = (account_state.message_index + 1) % len(messages_to_send)
                            account_state.message_sent_count = 0
                    
                    if not account_state.is_active:
                        break

                    self.logger.info(f"Цикл завершен. Готовимся к отдыху ({account_state.cycle_settings.rest_time_minutes}м)...", account_state.username)
                    
                    # --- Комментирование в перерыве ---
                    comm_sets = account_state.comment_settings
                    if datetime.now() - account_state.last_comment_time > timedelta(days=1):
                        account_state.comments_sent_24h = 0
                    
                    should_comment = (
                        comm_sets.enabled 
                        and account_state.comments_sent_24h < comm_sets.daily_limit
                        and comm_sets.targets_file 
                        and comm_sets.comments_file
                    )

                    time_spent_commenting = 0
                    if should_comment:
                        self.logger.info("Выполняем задачу комментирования...", account_state.username)
                        start_comm = time.time()
                        try:
                            with open(comm_sets.targets_file, 'r', encoding='utf-8') as f:
                                targets = [l.strip() for l in f if l.strip()]
                            with open(comm_sets.comments_file, 'r', encoding='utf-8') as f:
                                comments = [l.strip() for l in f if l.strip()]
                            
                            if targets and comments:
                                target = random.choice(targets)
                                comment_text = random.choice(comments)
                                final_comment = generate_unique_message_from_raw(
                                    comment_text, processor=twitter_ops.leetspeak_processor, leetspeak_probability=0.1
                                )
                                
                                photo_to_upload = None
                                if comm_sets.photo_path and os.path.exists(comm_sets.photo_path):
                                    if os.path.isdir(comm_sets.photo_path):
                                        images = [img for img in os.listdir(comm_sets.photo_path) if img.lower().endswith(('.png','.jpg','.jpeg'))]
                                        if images:
                                            photo_to_upload = os.path.join(comm_sets.photo_path, random.choice(images))
                                    else:
                                        photo_to_upload = comm_sets.photo_path
                                
                                success = await twitter_ops.post_comment_with_photo(
                                    account_state.browser, target, final_comment, photo_to_upload, account_state.username, account_manager
                                )
                                
                                if success:
                                    account_state.comments_sent_24h += 1
                                    account_state.last_comment_time = datetime.now()
                                    self.logger.info(f"Комментарий успешен! Всего сегодня: {account_state.comments_sent_24h}", account_state.username)
                        except Exception as e:
                            self.logger.error(f"Ошибка задачи комментирования: {e}", account_state.username)
                        
                        time_spent_commenting = time.time() - start_comm

                    remaining_rest = rest_time_seconds - time_spent_commenting
                    if remaining_rest > 0:
                        self.logger.info(f"Отдыхаем оставшиеся {remaining_rest:.1f}с...", account_state.username)
                        await asyncio.sleep(remaining_rest)
                    else:
                        self.logger.info("Комментирование заняло больше времени, чем отдых. Начинаем следующий цикл сразу.", account_state.username)

            except asyncio.CancelledError:
                self.logger.info(f"Цикл рассылки для {account_state.username} был отменен.", account_state.username)
            except Exception as e:
                self.logger.error(f"Ошибка в цикле отправки: {str(e)}", account_state.username)
            finally:
                account_state.is_mailing = False
                self.gui_update_callback()

    def start_account_cycle(self, account_state: AccountState, twitter_ops: TwitterOperations, account_manager: AccountManager, humanize: bool = True):
        with self.tasks_lock:
            if account_state.username in self.running_tasks:
                self.logger.warning("Задача отправки уже запущена для этого аккаунта", account_state.username)
                return
            
            async def wrapped_cycle():
                try:
                    await self.start_sending_cycle(account_state, twitter_ops, account_manager, humanize)
                except Exception as e:
                    self.logger.error(f"Критическая ошибка в цикле рассылки: {str(e)}", account_state.username)
                finally:
                    # Убедимся, что флаг сбрасывается даже при ошибке
                    account_state.is_mailing = False
                    # Удаляем из running_tasks
                    with self.tasks_lock:
                        if account_state.username in self.running_tasks:
                            del self.running_tasks[account_state.username]
                    # Обновляем GUI если коллбэк установлен
                    if self.gui_update_callback:
                        self.gui_update_callback()
            
            task = asyncio.create_task(wrapped_cycle())
            self.running_tasks[account_state.username] = task

    def stop_account_cycle(self, username: str):
        with self.tasks_lock:
            if username in self.running_tasks:
                # Set is_active to False to stop the loop
                if username in self.account_manager.accounts:
                    self.account_manager.accounts[username].is_active = False
                self.running_tasks[username].cancel()
                del self.running_tasks[username]
                self.logger.info(f"Остановлен цикл рассылки для {username}")

# --------------------- MonitorWindow ---------------------
class MonitorWindow:
    def __init__(self, master, logger: Logger, account_manager: AccountManager):
        self.master = master
        self.logger = logger
        self.account_manager = account_manager
        self.window = ctk.CTkToplevel(master)
        self.window.title("Accounts Monitor")
        center_window(self.window, 805, 455, offset_y=100)
        self.window.transient(master)
        self.window.lift()
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.common_info_text = ctk.CTkTextbox(self.window, height=60, font=ctk.CTkFont(size=14), wrap="word")
        self.common_info_text.pack(pady=(20,10), padx=5, fill="x")
        
        # Кнопка STAT убрана по запросу
        
        self.logs_text = tk.Text(self.window, height=12, wrap="word", bg="#2B2B2B", fg="white")
        self.logs_text.pack(pady=(10,20), padx=5, fill="both", expand=True)
        self.logs_text.config(state="disabled")
        self.logs_text.tag_config("error", foreground="red")
        self.logs_text.tag_config("warning", foreground="orange")
        self.logs_text.tag_config("info", foreground="green")
        self.logs_text.tag_config("account", foreground="blue")
        self.logs_text.tag_config("time", foreground="#C71585")
        copy_button = tk.Button(self.window, text="[COPY LOG]", command=self.copy_logs)
        copy_button.pack(pady=10)
        self.update_logs_periodically()
        self.update_monitor()

    def update_logs_periodically(self):
        self.refresh_logs()
        self.window.after(1000, self.update_logs_periodically)

    def refresh_logs(self):
        current_y = self.logs_text.yview()[0]
        logs = "\n".join(self.logger.log_buffer)
        self.logs_text.config(state="normal")
        self.logs_text.delete("1.0", tk.END)
        for line in logs.splitlines():
            tag = "info"
            if "Login failed" in line or "Error" in line:
                tag = "error"
            elif "Skipping retweet" in line or "Warning" in line:
                tag = "warning"
            self.logs_text.insert(tk.END, line + "\n", tag)
        self.logs_text.config(state="disabled")
        self.logs_text.yview_moveto(current_y)

    def copy_logs(self):
        self.master.clipboard_clear()
        logs = self.logs_text.get("1.0", tk.END)
        self.master.clipboard_append(logs)
        messagebox.showinfo("Info", "Логи скопированы в буфер обмена!")

    def on_close(self):
        self.window.withdraw()

    def show_stats(self):
        stat_win = ctk.CTkToplevel(self.master)
        stat_win.title(t("stat"))
        center_window(stat_win, 400, 300)
        stat_text = ctk.CTkTextbox(stat_win, font=ctk.CTkFont(size=12), wrap="word")
        stat_text.pack(pady=10, padx=10, fill="both", expand=True)
        lines = []
        for username, account in self.logger.config.__dict__.get("accounts", {}).items():
            line = f"@{username} - {account.messages_sent} сообщений - {account.retweets_count} ретвитов сделано"
            lines.append(line)
        stat_text.insert("1.0", "\n".join(lines))

    def update_monitor(self):
        try:
            active_accounts = 0
            total_messages = 0
            total_retweets = 0
            total_comments = 0

            for acc in self.account_manager.accounts.values():
                if acc.browser is None:
                    acc.is_active = False
                    acc.is_paused = False
                
                if acc.is_active:
                    active_accounts += 1
                
                total_messages += acc.messages_sent
                total_retweets += acc.retweets_count
                total_comments += acc.comments_sent_24h

            if self.window.winfo_exists():
                info = (f"ACT: {active_accounts}   "
                        f"MSG: {total_messages}   "
                        f"RT: {total_retweets}   "
                        f"COMM: {total_comments}")
                
                self.common_info_text.delete("1.0", tk.END)
                self.common_info_text.insert(tk.END, info)
                self.window.after(5000, self.update_monitor)
        except Exception as e:
            self.logger.error(f"Ошибка обновления монитора: {e}")

# --------------------- GlobalStatsWindow (Updated: Quick Filters + CSV Fix) ---------------------
class GlobalStatsWindow:
    def __init__(self, master, stats_manager: StatsManager):
        self.stats_manager = stats_manager
        self.window = ctk.CTkToplevel(master)
        self.window.title("📊 Global Statistics History")
        center_window(self.window, 1050, 650)
        self.window.transient(master)
        self.window.grab_set()

        # --- БЛОК 1: БЫСТРЫЕ ФИЛЬТРЫ (КНОПКИ) ---
        # Панель с кнопками, чтобы не вводить даты вручную
        quick_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        quick_frame.pack(pady=(15, 0), padx=10, fill="x")
        
        ctk.CTkLabel(quick_frame, text="Quick Filters:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=5)
        
        # [Today] - Ставит "Сегодня" - "Сегодня"
        btn_today = ctk.CTkButton(quick_frame, text="Today", width=80, height=28, 
                                  command=lambda: self.apply_quick_filter(0, single_day=True))
        btn_today.pack(side="left", padx=5)
        
        # [Yesterday] - Ставит "Вчера" - "Вчера"
        btn_yest = ctk.CTkButton(quick_frame, text="Yesterday", width=90, height=28, 
                                 command=lambda: self.apply_quick_filter(1, single_day=True))
        btn_yest.pack(side="left", padx=5)
        
        # [Last 7 Days] - Ставит "7 дней назад" - "Сегодня"
        btn_week = ctk.CTkButton(quick_frame, text="Last 7 Days", width=100, height=28, 
                                 command=lambda: self.apply_quick_filter(7, single_day=False))
        btn_week.pack(side="left", padx=5)
        
        # [Last 30 Days] - Ставит "30 дней назад" - "Сегодня"
        btn_month = ctk.CTkButton(quick_frame, text="Last 30 Days", width=100, height=28, 
                                  command=lambda: self.apply_quick_filter(30, single_day=False))
        btn_month.pack(side="left", padx=5)

        # --- БЛОК 2: ПОЛЯ ВВОДА И ЭКСПОРТ ---
        filter_frame = ctk.CTkFrame(self.window)
        filter_frame.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(filter_frame, text="From:").pack(side="left", padx=5)
        self.entry_start = ctk.CTkEntry(filter_frame, width=100, placeholder_text="DD.MM.YYYY")
        self.entry_start.pack(side="left", padx=5)
        
        # По умолчанию ставим 30 дней
        default_start = (datetime.now() - timedelta(days=30)).strftime("%d.%m.%Y")
        self.entry_start.insert(0, default_start)

        ctk.CTkLabel(filter_frame, text="To:").pack(side="left", padx=5)
        self.entry_end = ctk.CTkEntry(filter_frame, width=100, placeholder_text="DD.MM.YYYY")
        self.entry_end.pack(side="left", padx=5)
        self.entry_end.insert(0, datetime.now().strftime("%d.%m.%Y"))

        # Кнопка ручного обновления (если ввели даты руками)
        btn_refresh = ctk.CTkButton(filter_frame, text="🔄 Refresh Table", width=120, command=self.load_stats)
        btn_refresh.pack(side="left", padx=15)
        
        # Кнопка CSV Export (Зеленая)
        btn_csv = ctk.CTkButton(filter_frame, text="💾 Export CSV", width=120, fg_color="#27ae60", hover_color="#2ecc71",
                                command=self.export_to_csv)
        btn_csv.pack(side="right", padx=10)

        # --- БЛОК 3: ТАБЛИЦА ---
        headers_frame = ctk.CTkFrame(self.window, height=40, fg_color="transparent")
        headers_frame.pack(fill="x", padx=10, pady=(10, 0))
        
        # Конфигурация колонок (Название, Ширина)
        self.columns_config = [
            ("Username", 180), 
            ("MSG (Period)", 90), ("RT (Period)", 90), ("Comm (Period)", 100),
            ("MSG (Total)", 90), ("RT (Total)", 90), ("Comm (Total)", 100),
            ("Action", 80)
        ]
        
        for col_name, width in self.columns_config:
            lbl = ctk.CTkLabel(headers_frame, text=col_name, width=width, font=ctk.CTkFont(weight="bold"))
            lbl.pack(side="left", padx=2)

        self.scroll_frame = ctk.CTkScrollableFrame(self.window)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Переменная для хранения текущих данных (чтобы экспортировать именно то, что видим)
        self.current_data_view = []

        # Загружаем данные сразу при открытии
        self.load_stats()

    def apply_quick_filter(self, days_offset: int, single_day: bool = False):
        """
        Логика кнопок быстрого выбора дат.
        single_day=True -> Для кнопок "Today" и "Yesterday" (Начало и Конец = один и тот же день)
        single_day=False -> Для кнопок "Week" и "Month" (Диапазон от N дней назад до Сегодня)
        """
        now = datetime.now()
        
        if single_day:
            # Если "Вчера", то и начало вчера, и конец вчера
            target_date = now - timedelta(days=days_offset)
            start_str = target_date.strftime("%d.%m.%Y")
            end_str = target_date.strftime("%d.%m.%Y")
        else:
            # Если "Неделя", то начало -7 дней, конец - сегодня
            start_date = now - timedelta(days=days_offset)
            start_str = start_date.strftime("%d.%m.%Y")
            end_str = now.strftime("%d.%m.%Y")

        # Очищаем поля и вставляем новые даты
        self.entry_start.delete(0, "end")
        self.entry_start.insert(0, start_str)
        
        self.entry_end.delete(0, "end")
        self.entry_end.insert(0, end_str)
        
        # Автоматически обновляем таблицу
        self.load_stats()

    def delete_stat(self, username):
        if messagebox.askyesno("Delete Stats", f"Permanently delete stats for @{username}?"):
            self.stats_manager.delete_stats_for_user(username)
            self.load_stats()

    def load_stats(self):
        # Очистка таблицы
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        start_str = self.entry_start.get()
        end_str = self.entry_end.get()

        try:
            start_date = datetime.strptime(start_str, "%d.%m.%Y")
            end_date = datetime.strptime(end_str, "%d.%m.%Y").replace(hour=23, minute=59, second=59)
        except ValueError:
            messagebox.showerror("Error", "Invalid date format. Use DD.MM.YYYY")
            return

        # Получаем данные
        data = self.stats_manager.get_detailed_stats(start_date, end_date)
        data.sort(key=lambda x: x['msg_period'], reverse=True)
        
        # Сохраняем в переменную класса для CSV экспорта
        self.current_data_view = data 

        totals = {"msg_p": 0, "rt_p": 0, "comm_p": 0, "msg_t": 0, "rt_t": 0, "comm_t": 0}
        widths = [w for _, w in self.columns_config]

        # Рисуем строки
        for i, row in enumerate(data):
            row_frame = ctk.CTkFrame(self.scroll_frame)
            row_frame.pack(fill="x", pady=2)
            
            # Чередование цветов строк
            bg_color = "transparent" if i % 2 == 0 else ("#2e2e2e" if ctk.get_appearance_mode()=="Dark" else "#e0e0e0")
            row_frame.configure(fg_color=bg_color)

            vals = [
                f"@{row['username']}",
                str(row['msg_period']), str(row['rt_period']), str(row['comm_period']),
                str(row['msg_total']), str(row['rt_total']), str(row['comm_total'])
            ]
            
            # Подсчет итогов
            totals["msg_p"] += row['msg_period']
            totals["rt_p"] += row['rt_period']
            totals["comm_p"] += row['comm_period']
            totals["msg_t"] += row['msg_total']
            totals["rt_t"] += row['rt_total']
            totals["comm_t"] += row['comm_total']

            # Ячейки с данными
            for j, val in enumerate(vals):
                lbl = ctk.CTkLabel(row_frame, text=val, width=widths[j])
                lbl.pack(side="left", padx=2)

            # Кнопка удаления
            btn_del = ctk.CTkButton(row_frame, text="Delete", width=widths[-1], fg_color="#c0392b", hover_color="#e74c3c",
                                    command=lambda u=row['username']: self.delete_stat(u))
            btn_del.pack(side="left", padx=2)

        # Строка ИТОГО (Footer)
        divider = ctk.CTkFrame(self.scroll_frame, height=2, fg_color="gray")
        divider.pack(fill="x", pady=5)
        
        total_frame = ctk.CTkFrame(self.scroll_frame)
        total_frame.pack(fill="x", pady=5)
        
        total_vals = [
            "TOTAL:",
            str(totals["msg_p"]), str(totals["rt_p"]), str(totals["comm_p"]),
            str(totals["msg_t"]), str(totals["rt_t"]), str(totals["comm_t"]), ""
        ]
        
        for j, val in enumerate(total_vals):
            lbl = ctk.CTkLabel(total_frame, text=val, width=widths[j], font=ctk.CTkFont(weight="bold"))
            lbl.pack(side="left", padx=2)

    def export_to_csv(self):
        """Функция экспорта текущей таблицы в CSV файл"""
        if not self.current_data_view:
            messagebox.showwarning("Export", "No data to export. Try changing filters.")
            return

        # Предлагаем имя файла на основе дат
        start_str = self.entry_start.get().replace(".", "-")
        end_str = self.entry_end.get().replace(".", "-")
        default_filename = f"stats_{start_str}_{end_str}.csv"

        filename = fd.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile=default_filename,
            title="Export Statistics"
        )

        if not filename:
            return

        try:
            # ИСПОЛЬЗУЕМ delimiter=';' и encoding='utf-8-sig' для Excel
            with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['Username', 'MSG (Period)', 'RT (Period)', 'Comm (Period)', 
                              'MSG (Total)', 'RT (Total)', 'Comm (Total)']
                
                # Указываем разделитель точку с запятой
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')

                writer.writeheader()
                for row in self.current_data_view:
                    writer.writerow({
                        'Username': row['username'],
                        'MSG (Period)': row['msg_period'],
                        'RT (Period)': row['rt_period'],
                        'Comm (Period)': row['comm_period'],
                        'MSG (Total)': row['msg_total'],
                        'RT (Total)': row['rt_total'],
                        'Comm (Total)': row['comm_total']
                    })
            
            messagebox.showinfo("Export", f"Successfully exported {len(self.current_data_view)} rows to CSV!")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to save CSV: {e}")
            
# --------------------- GUI ---------------------
class GUI:
    def __init__(self):
        self.app_is_authorized = False
        self.expiration_date = None
        
        # Создаем временное окно для диалога лицензии
        root_for_dialogs = ctk.CTk()
        root_for_dialogs.withdraw()

        dialog = ctk.CTkInputDialog(text="Please enter your license key:", title="License check")
        user_key = dialog.get_input()

        if not user_key:
            messagebox.showerror("Error!", "The key was not entered. The program will be closed.")
            root_for_dialogs.destroy()
            return

        is_valid, message, expiration_dt = verify_license(user_key)

        if not is_valid:
            messagebox.showerror("License error", message)
            root_for_dialogs.destroy()
            return

        messagebox.showinfo("Done!", message)
        root_for_dialogs.destroy()
        self.app_is_authorized = True
        self.expiration_date = expiration_dt

        self.config = Config()
        self.logger = Logger(self.config)
        self.stats_manager = StatsManager(self.config)
        self.account_manager = AccountManager(self.config, self.logger)
        self.message_manager = MessageManager(self.config, self.logger)
        self.cycle_manager = CycleManager(self.config, self.logger)
        self.comment_manager = CommentManager(self.config, self.logger) # NEW
        self.twitter_ops = TwitterOperations(self.logger, self.stats_manager)
        self.task_scheduler = TaskScheduler(self.logger, self.update_account_table_threadsafe, self.account_manager)
        self.selected_accounts = {}
        
        # --- Telegram Bot ---
        self.telegram_bot_instance = None
        self.telegram_bot_thread = None
        
        # --- GUI OPTIMIZATION STORAGE ---
        self.row_widgets = {} # {username: {frame, status, groups, last}}
        
        # --- Auto refresh control ---
        self._stop_auto_refresh = False
        self._after_ids = []
        
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        
        self.setup_main_window()
        
        # Устанавливаем связь между менеджером аккаунтов и GUI
        self.account_manager.set_gui_instance(self)
        
        if self.expiration_date:
            date_str = self.expiration_date.strftime("%d,%m,%y")
            time_str = self.expiration_date.strftime("%I:%M %p").lstrip('0').lower()
            self.license_label.configure(text=f"Expired: {date_str} at {time_str}")

            # ЗАПУСК ПРОВЕРКИ ЛИЦЕНЗИИ (Каждые 6000 сек)
            self.start_license_monitoring()
            
        # START AUTO REFRESH
        self.auto_refresh_loop()
        
        # ЗАПУСК TELEGRAM БОТА
        self.setup_telegram_bot(expiration_dt)

    def setup_telegram_bot(self, expiration_date):
        """Настройка и запуск Telegram бота"""
        try:
            # Конфигурация бота
            bot_config = BotConfig(
                token=TELEGRAM_BOT_TOKEN,
                chat_id=TELEGRAM_CHAT_ID,
                enable_auto_reports=True,
                report_interval=3600,  # 1 час
                enable_error_alerts=True,
                enable_startup_notification=True
            )
            
            # Передаем зависимости
            self.telegram_bot_instance.set_dependencies(
                account_manager=self.account_manager,
                stats_manager=self.stats_manager,
                license_info={
                    'expiration_date': expiration_date.strftime("%d.%m.%Y %H:%M"),
                    'days_left': (expiration_date - datetime.now()).days
                },
                gui_instance=self
            )
            # Запускаем бота в отдельном потоке
            if hasattr(self.telegram_bot_instance, 'start_bot'):
                self.telegram_bot_instance.start_bot()
            else:
                self.logger.error("TelegramBotManager не имеет метода start_bot")

            # Передаем бота в task_scheduler
            self.task_scheduler.set_telegram_bot(self.telegram_bot_instance)

            
            self.logger.info("Telegram bot инициализирован и запущен")
            
        except Exception as e:
            self.logger.error(f"Не удалось настроить Telegram бота: {e}")
            print(f"⚠️ Не удалось настроить Telegram бота: {e}")

    def start_license_monitoring(self):
        # Запускаем цикл проверки. 6000 секунд = 6 000 000 миллисекунд
        self.window.after(6000000, self.check_license_timer)

    def check_license_timer(self):
        """Периодическая проверка лицензии"""
        if self.expiration_date and datetime.now() > self.expiration_date:
            # ЛИЦЕНЗИЯ ИСТЕКЛА
            self.logger.error("Лицензия истекла во время проверки. Завершение работы.")
            
            # Отправляем уведомление в Telegram
            if self.telegram_bot_instance and self.telegram_bot_instance.running:
                try:
                    # Создаем задачу для отправки уведомления
                    asyncio.run_coroutine_threadsafe(
                        self.telegram_bot_instance.send_error_alert("LICENSE_EXPIRED", "", "Лицензия истекла"),
                        self.telegram_bot_instance.loop
                    ).result(timeout=5)
                except:
                    pass
            
            # 1. Закрываем браузеры
            try:
                self.account_manager.shutdown_all_browsers()
            except Exception:
                pass
            
            # 2. Убиваем процессы
            force_kill_chromedrivers()
            
            # 3. Показываем сообщение
            messagebox.showerror("License Expired", "Ваша лицензия истекла! Программа будет закрыта.")
            
            # 4. Полный выход
            self.window.destroy()
            sys.exit(0)
        else:
            # Если все ок, планируем следующую проверку через 6000 секунд
            self.window.after(6000000, self.check_license_timer)

    def update_account_table_threadsafe(self):
        self.window.after(0, self.update_account_table)

    def setup_main_window(self):
        self.window = ctk.CTk()
        self.window.title("X-Genius Pro 🧠 2026")
        
        self.window.protocol("WM_DELETE_WINDOW", self.on_app_close)
        
        self.window.minsize(1350, 740)
        
        # --- VIRTUALIZATION VARS ---
        self.visible_rows_count = 18  # Сколько строк влезает в экран физически
        self.row_pool = []            # Список виджетов (пул)
        self.scroll_start_index = 0   # С какого индекса начинаем показ
        self.filtered_accounts = []   # Текущий список данных
        # ---------------------------
        
        center_window(self.window, 1400, 740)
        title_label = ctk.CTkLabel(self.window, text="X-Genius Pro 🧠 2026", font=ctk.CTkFont(family="Berlin Sans FB Demi", size=25, weight="bold"))
        title_label.pack(pady=12)
        self.setup_top_buttons()
        self.setup_summary_panel()
        button_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        button_frame.pack(pady=5)
        add_acc_button = ctk.CTkButton(button_frame, text=t("add_account"), command=self.open_add_account_window, font=ctk.CTkFont(size=14))
        add_acc_button.pack(side="left", padx=5)
        import_acc_button = ctk.CTkButton(button_frame, text="📥 Import Accounts", command=self.open_import_accounts_window, font=ctk.CTkFont(size=14))
        import_acc_button.pack(side="left", padx=5)
        self.setup_account_table()
        
    def on_app_close(self):
        if messagebox.askokcancel("Exit", "Close application and kill all sessions?"):
            # Stop auto refresh loop first
            self._stop_auto_refresh = True
            
            try:
                self.account_manager.shutdown_all_browsers()
            except Exception:
                pass
            
            # Останавливаем Telegram бота
            if self.telegram_bot_instance:
                self.telegram_bot_instance.stop_bot()
            
            # Cancel all scheduled after events
            for after_id in self._after_ids:
                try:
                    self.window.after_cancel(after_id)
                except Exception:
                    pass
            self._after_ids.clear()
            
            self.window.destroy()
            force_kill_chromedrivers()
            sys.exit(0)

    # === ИЗМЕНЕНО: КНОПКИ В 2 РЯДА ===
    def setup_top_buttons(self):
        # --- СТРОКА 1: Основные действия ---
        row1_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        row1_frame.pack(side="top", fill="x", padx=5, pady=(5, 2))
        
        btn_close_all = ctk.CTkButton(row1_frame, text=t("close_all"), command=self.close_all_sessions, width=90, fg_color="#c0392b", hover_color="#e74c3c")
        btn_close_all.pack(side="left", padx=2)
        
        btn_close_sel = ctk.CTkButton(row1_frame, text="🔒 Close Sel", command=self.close_selected_sessions, width=90, fg_color="#c0392b", hover_color="#e74c3c")
        btn_close_sel.pack(side="left", padx=2)
        
        # --- КНОПКА: Удалить выбранные ---
        btn_del_select = ctk.CTkButton(row1_frame, text=t("del_select"), command=self.delete_selected_accounts, width=90, fg_color="#e74c3c", hover_color="#c0392b")
        btn_del_select.pack(side="left", padx=2)
        
        btn_select_start = ctk.CTkButton(row1_frame, text=t("select_to_start"), command=self.select_to_start, width=120)
        btn_select_start.pack(side="left", padx=2)

        btn_bulk_edit = ctk.CTkButton(row1_frame, text=t("bulk_edit"), command=self.open_bulk_edit_window, width=100)
        btn_bulk_edit.pack(side="left", padx=2)

        btn_mass_msg_edit = ctk.CTkButton(row1_frame, text=t("mass_msg_edit"), command=self.open_mass_message_edit_window, width=120)
        btn_mass_msg_edit.pack(side="left", padx=2)
        
        # --- НОВАЯ КНОПКА: Экспорт чатов ---
        btn_export_chats = ctk.CTkButton(row1_frame, text="📤 Export Chats", command=self.export_chats_selected, 
                                           width=110, fg_color="#8e44ad", hover_color="#9b59b6")
        btn_export_chats.pack(side="left", padx=2)
        
        btn_mailing_sel = ctk.CTkButton(row1_frame, text="🚀 Mailing Sel", command=self.start_mailing_for_selected, width=120)
        btn_mailing_sel.pack(side="left", padx=2)

        btn_pause_sel = ctk.CTkButton(row1_frame, text="⏸ Pause Sel", command=self.pause_selected_sessions, width=110, fg_color="#e67e22", hover_color="#d35400")
        btn_pause_sel.pack(side="left", padx=2)
        
        btn_auto_parse = ctk.CTkButton(row1_frame, text="🔍 Auto Parse", command=self.start_auto_parse_selected, width=110, fg_color="#8e44ad", hover_color="#9b59b6")
        btn_auto_parse.pack(side="left", padx=2)
        
        btn_mailing_ready = ctk.CTkButton(row1_frame, text="🚀 Mail Ready", command=self.start_mailing_for_ready, width=110)
        btn_mailing_ready.pack(side="left", padx=2)

        # --- СТРОКА 2: Статистика, Фильтры, Тема ---
        row2_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        row2_frame.pack(side="top", fill="x", padx=5, pady=(2, 5))

        btn_global_stat = ctk.CTkButton(row2_frame, text="📊 History", command=self.open_global_stats, width=90)
        btn_global_stat.pack(side="left", padx=2)
        
        btn_monitor = ctk.CTkButton(row2_frame, text="Monitor", command=self.open_monitor_window, width=90)
        btn_monitor.pack(side="left", padx=2)
        
        # Anti-spam manual refresh
        def on_manual_refresh():
            self.btn_refresh.configure(state="disabled")
            for username, state in self.account_manager.accounts.items():
                if state.browser and state.is_active:
                    if state.status_reason in ["Error", "LOCKED", "EMAIL LOCK", "LOCKED (CAPTCHA)"]:
                         state.status_reason = "" 
                         self.logger.info(f"Статус сброшен вручную через Refresh", username)
            self.update_account_table()
            self.window.after(1000, lambda: self.btn_refresh.configure(state="normal"))

        self.btn_refresh = ctk.CTkButton(row2_frame, text=t("refresh"), command=on_manual_refresh, width=90)
        self.btn_refresh.pack(side="left", padx=2)
        
        btn_help = ctk.CTkButton(row2_frame, text=t("help"), command=self.show_help, width=60)
        btn_help.pack(side="left", padx=2)
        
        # ПРАВАЯ ЧАСТЬ ВТОРОЙ СТРОКИ (Фильтры и Тема)
        self.theme_switch = ctk.CTkSwitch(row2_frame, text="", command=self.update_theme_from_switch, width=40)
        self.theme_switch.pack(side="right", padx=5)
        
        theme_label = ctk.CTkLabel(row2_frame, text="Theme", width=50)
        theme_label.pack(side="right", padx=0)
        
        self.license_label = ctk.CTkLabel(row2_frame, text="License: Checking...", text_color="gray")
        self.license_label.pack(side="right", padx=15)
        
        # --- ФИЛЬТР ГРУПП ТЕПЕРЬ ТОЧНО ВЛЕЗЕТ ---
        self.group_filter_var = tk.StringVar(value="All Accounts")
        self.group_filter_menu = ctk.CTkOptionMenu(row2_frame, variable=self.group_filter_var, command=lambda _: self.update_account_table(), width=180)
        self.group_filter_menu.pack(side="right", padx=10)
        
        group_label = ctk.CTkLabel(row2_frame, text="Filter by Group:", font=ctk.CTkFont(weight="bold"))
        group_label.pack(side="right", padx=5)
    # =================================

    def open_global_stats(self):
        GlobalStatsWindow(self.window, self.stats_manager)

    def update_theme_from_switch(self):
        if self.theme_switch.get():
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

    def setup_summary_panel(self):
        self.summary_label = ctk.CTkLabel(self.window, text=f"{t('summary')} 0 MSG, 0 RT, 0 Comm, 0 Groups", font=ctk.CTkFont(size=14))
        self.summary_label.pack(pady=5)
        self.update_summary()

    def update_summary(self):
        # Загружаем ВСЕ аккаунты из файла
        all_accounts_data = self.account_manager.load_accounts()
        
        # Объединяем с состояниями из памяти для получения актуальных статусов
        accounts_in_memory = self.account_manager.accounts
        
        total_messages = 0
        total_retweets = 0
        total_comments = 0
        total_groups = 0
        
        all_accounts = len(all_accounts_data)
        paused_accounts = 0
        error_accounts = 0
        ready_accounts = 0
        
        for acc in all_accounts_data:
            username = acc.get('username', '')
            
            # Проверяем есть ли состояние в памяти
            state = accounts_in_memory.get(username)
            
            # Получаем актуальные значения из памяти или файла
            is_active = state.is_active if state else acc.get('is_active', False)
            is_paused = state.is_paused if state else acc.get('is_paused', False)
            status_reason = state.status_reason if state else acc.get('status_reason', 'ACTIVE')
            groups = state.groups if state and state.groups else acc.get('groups', [])
            messages_sent = state.messages_sent if state else acc.get('messages_sent', 0)
            retweets_count = state.retweets_count if state else acc.get('retweets_count', 0)
            comments_count = state.comments_sent_24h if state else acc.get('comments_sent_24h', 0)
            
            total_messages += messages_sent
            total_retweets += retweets_count
            total_comments += comments_count
            total_groups += len(groups)
            
            if is_paused:
                paused_accounts += 1
            elif status_reason in ['SUSPENDED', 'LOCKED', 'ERROR', 'AUTH_FAILED', 'NEED_RELOGIN']:
                error_accounts += 1
            elif is_active and len(groups) > 0:
                ready_accounts += 1
        
        inactive_accounts = all_accounts - paused_accounts - error_accounts - ready_accounts
        
        # Формат: 2 строки
        stats_line = f"{t('summary')} {total_messages} MSG, {total_retweets} RT, {total_comments} Comm"
        accs_line = f" Acc's: ALL:{all_accounts} PAU:{paused_accounts} ERR:{error_accounts} RDY:{ready_accounts} INA:{inactive_accounts}, {total_groups} Groups"
        
        summary_text = stats_line + "\n" + accs_line
        self.summary_label.configure(text=summary_text)
        self.window.after(5000, self.update_summary)

    def show_help(self):
        help_window = ctk.CTkToplevel(self.window)
        help_window.title("Help - X-Genius Pro 🧠 2026")
        help_window.geometry("700x600")
        help_text = (
            "🧠 X-GENIUS PRO 🧠 2026 — ПОЛНОЕ РУКОВОДСТВО ПОЛЬЗОВАТЕЛЯ\n\n"
            "Программа автоматизирует работу в Twitter (X): рассылки в ЛС, ретвиты, умные комментарии и фарм аккаунтов.\n"
            "Для поддержки пишите: https://t.me/zeus4308\n\n"
            
            "══════════════════════════════════════════════════\n"
            "1. 🔝 ВЕРХНЕЕ МЕНЮ (МАССОВОЕ УПРАВЛЕНИЕ)\n"
            "══════════════════════════════════════════════════\n\n"
            
            "🔒 [Close All]\n"
            "   Экстренное выключение. Мгновенно закрывает ВСЕ открытые браузеры и останавливает все процессы.\n\n"
            "🔒 [Close Selected]\n"
            "   Закрывает браузеры только у тех аккаунтов, где вы поставили галочку (слева в таблице).\n\n"
            "✔️ [Select to Start]\n"
            "   Массовый вход. Отметьте галочками нужные аккаунты, нажмите кнопку, и бот по очереди (раз в 15 сек)\n"
            "   откроет браузеры и войдет в аккаунты.\n\n"
            "📝 [Bulk Edit]\n"
            "   Массовое изменение данных. Позволяет сменить Прокси или Группу сразу для кучи выделенных аккаунтов.\n\n"
            "📝 [Mass MSG Edit]\n"
            "   Массовая настройка задач. Вы настраиваете текст рассылки и задержки один раз, а применяются они\n"
            "   ко всем выделенным аккаунтам сразу.\n\n"
            "📤 [Export Chats] - НОВАЯ ФУНКЦИЯ\n"
            "   Экспорт информации о чатах. Выберите аккаунты и экспортируйте список всех их чатов в текстовый файл.\n\n"
            "🚀 [Mailing Selected]\n"
            "   Запускает рассылку только на отмеченных галочкой аккаунтах (они должны быть уже залогинены).\n\n"
            "🚀 [Mailing for Ready]\n"
            "   Умный запуск. Бот сам найдет все аккаунты, которые 'готовы' (Готов = Статус Active + Есть группы + Есть текст)\n"
            "   и запустит на них работу.\n\n"
            "📊 [History]\n"
            "   Глобальная статистика. Показывает таблицу успехов за выбранный период (сообщения, ретвиты, комменты).\n\n"
            "🖥 [Monitor]\n"
            "   Живой лог. Окно, где пишется каждое действие бота в реальном времени.\n\n"
            
            "══════════════════════════════════════════════════\n"
            "2. 📋 ТАБЛИЦА (УПРАВЛЕНИЕ ОДНИМ АККАУНТОМ)\n"
            "══════════════════════════════════════════════════\n\n"
            "🔲 [Чекбокс] — Выделить аккаунт для массовых действий.\n\n"
            "🔑 [Login]\n"
            "   Открывает Chrome, загружает куки и входит в профиль. Ждите зеленый статус 'Active'.\n\n"
            "👀 [View] (Глаз)\n"
            "   Найти потерянное окно. Если браузеров много, нажмите, чтобы вывести окно этого аккаунта на передний план.\n\n"
            "🔍 [Parse] (Парсинг)\n"
            "   Сканирует личные сообщения (DM). Бот листает диалоги, находит групповые чаты и сохраняет их в базу.\n"
            "   Нужно делать 1 раз перед первой рассылкой.\n\n"
            "📨 [Mailing] (Рассылка)\n"
            "   Запускает главный рабочий цикл: Отправка сообщений -> Ретвиты -> Отдых -> Повтор.\n\n"
            "✏️ [Edit]\n"
            "   Редактировать Логин, Пароль, Прокси или Группу аккаунта.\n\n"
            "⚙️ [Settings]\n"
            "   Настройка рассылки для этого аккаунта:\n"
            "   - Msg cycle: Сколько сообщений слать за раз.\n"
            "   - Rest time: Время отдыха (в минутах).\n"
            "   - Mailing Messages: Тексты сообщений (поддерживает рандомизацию).\n\n"
            "💬 [Comm] (Комментарии)\n"
            "   Настройка авто-комментинга. Укажите файлы со списком юзеров и текстами.\n"
            "   Бот будет комментировать их во время паузы (Rest time).\n\n"
            "⏸ [S] (Stop) — Поставить аккаунт на паузу.\n"
            "▶️ [R] (Resume) — Снять с паузы.\n"
            "📊 [Stat] — Показать статистику этого аккаунта за сегодня (24ч).\n\n"
            "❌ [Close]\n"
            "   Закрывает браузер и СБРАСЫВАЕТ ОШИБКУ (очищает красный статус).\n\n"
            "🗑 [Delete] — Удалить аккаунт из программы навсегда.\n\n"
            
            "══════════════════════════════════════════════════\n"
            "3. ⚙️ ЛОГИКА РАБОТЫ (КАК ЭТО РАБОТАЕТ)\n"
            "══════════════════════════════════════════════════\n\n"
            "🔄 ЦИКЛ РАССЫЛКИ (Mailing):\n"
            "   1. Бот заходит в найденную группу.\n"
            "   2. Пишет текст (уникализирует буквы и смайлы).\n"
            "   3. Если включено, отправляет GIF.\n"
            "   4. Отправляет N сообщений (настройка Msg cycle).\n"
            "   5. Делает ретвиты (если настроено).\n"
            "   6. Уходит на 'Отдых' (Rest time).\n\n"
            "💬 КОММЕНТИНГ (Smart Comments):\n"
            "   Работает ТОЛЬКО во время 'Отдыха' между рассылками.\n"
            "   1. Бот берет юзера из вашего файла (Targets).\n"
            "   2. Идет к нему в профиль.\n"
            "   3. Находит закрепленный или последний твит.\n"
            "   4. Пишет коммент (из файла) + прикрепляет фото (из папки).\n\n"
            
            "══════════════════════════════════════════════════\n"
            "4. 🚦 СТАТУСЫ И ОШИБКИ (НОВЫЕ!)\n"
            "══════════════════════════════════════════════════\n\n"
            "🟢 Active — Все отлично, аккаунт готов.\n"
            "🔵 Mailing — Идет работа.\n"
            "🟠 Paused — Аккаунт на ручной паузе.\n"
            "🟣 NEED RELOGIN — Аккаунт разлогинился, требуется перелогин.\n"
            "🔴 SUSPENDED — Аккаунт забанен Твиттером навсегда.\n"
            "🔴 LOCKED / CAPTCHA — Твиттер просит подтвердить, что вы человек. Нужно зайти руками.\n"
            "🔴 DM LIMIT 4H — Лимит на отправку сообщений. Бот сам поставил паузу на 4 часа, потом продолжит.\n\n"
            
            "══════════════════════════════════════════════════\n"
            "5. 📂 ФАЙЛЫ ОТЧЕТОВ (папка logs)\n"
            "══════════════════════════════════════════════════\n"
            "📄 retweets_success.txt — Список: [Дата] Кто ретвитнул -> Кого.\n"
            "📄 comments_success.txt — Список: [Дата] Кто комментировал -> Кого.\n"
            "📄 groups_export_дата.txt — Экспорт чатов выбранных аккаунтов.\n"
            "📄 bot_дата.log — Полный технический лог.\n"
        )
        text_box = ctk.CTkTextbox(help_window, width=670, height=500, font=("Arial", 12))
        text_box.pack(pady=10, padx=10, fill="both", expand=True)
        text_box.insert("1.0", help_text)
        text_box.configure(state="disabled")
        help_window.focus_set()
        help_window.grab_set()

    def export_chats_selected(self):
        """Экспорт информации о чатах выбранных аккаунтов"""
        accounts = self.account_manager.load_accounts()
        selected_usernames = [acc["username"] for acc in accounts if self.selected_accounts.get(acc["username"], tk.BooleanVar()).get()]
        
        if not selected_usernames:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return
        
        # Проверяем, есть ли у выбранных аккаунтов сохраненные группы
        accounts_with_groups = []
        for username in selected_usernames:
            if username in self.account_manager.accounts:
                if self.account_manager.accounts[username].groups:
                    accounts_with_groups.append(username)
            else:
                # Пытаемся загрузить из сохраненных
                saved_groups = self.account_manager.load_saved_groups(username)
                if saved_groups:
                    accounts_with_groups.append(username)
        
        if not accounts_with_groups:
            messagebox.showwarning("Warning", "У выбранных аккаунтов нет сохраненных чатов!")
            return
        
        confirm = messagebox.askyesno("Confirm", f"Экспортировать информацию о чатах для {len(selected_usernames)} аккаунтов?\n"
                                                 f"Аккаунты с группами: {len(accounts_with_groups)}")
        if confirm:
            try:
                export_path = self.account_manager.export_groups_to_file(selected_usernames)
                messagebox.showinfo("Успех", f"Информация о чатах экспортирована в файл:\n{export_path}")
                
                # Предлагаем открыть файл
                if messagebox.askyesno("Открыть файл", "Хотите открыть экспортированный файл?"):
                    try:
                        if sys.platform == "win32":
                            os.startfile(export_path)
                        elif sys.platform == "darwin":
                            subprocess.call(["open", export_path])
                        else:
                            subprocess.call(["xdg-open", export_path])
                    except Exception as e:
                        messagebox.showwarning("Ошибка", f"Не удалось открыть файл: {e}")
                        
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось экспортировать чаты: {e}")

    def close_all_sessions(self):
        for acc_state in self.account_manager.accounts.values():
            if acc_state.browser:
                try:
                    acc_state.browser.quit()
                except Exception:
                    pass
                acc_state.browser = None
            acc_state.is_active = False
            acc_state.is_paused = False
            acc_state.is_mailing = False
        for username in list(self.task_scheduler.running_tasks.keys()):
            self.task_scheduler.stop_account_cycle(username)
        messagebox.showinfo("Info", "All sessions closed! 🚪")
        self.update_account_table()

    def close_selected_sessions(self):
        """Закрывает сессии только для выбранных (чекбокс) аккаунтов"""
        accounts = self.account_manager.load_accounts()
        selected = [acc["username"] for acc in accounts if self.selected_accounts.get(acc["username"], tk.BooleanVar()).get()]
        
        if not selected:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return
            
        for username in selected:
            self.close_account(username)
            
        messagebox.showinfo("Info", f"Closed sessions for {len(selected)} selected accounts.")

    def close_account(self, username: str):
        account_state = self.account_manager.accounts.get(username)
        if account_state:
            if username in self.task_scheduler.running_tasks:
                self.task_scheduler.stop_account_cycle(username)
            if account_state.browser:
                try:
                    account_state.browser.quit()
                except Exception as e:
                    self.logger.error(f"Error quitting browser for {username}: {e}", username)
            account_state.browser = None
            account_state.is_active = False
            account_state.is_paused = False
            account_state.is_mailing = False
            account_state.need_relogin = False  # Сбрасываем флаг перелогина
            account_state.status_reason = ""
            self.logger.info(f"Browser session ended for {username}", username)
            self.update_account_table()
        else:
            self.logger.warning(f"No active browser for {username}", username)

    def pause_account(self, username: str):
        account_state = self.account_manager.accounts.get(username)
        if account_state and account_state.is_active and not account_state.is_paused:
            account_state.is_paused = True
            self.logger.info(f"Paused mailing cycle for {username}", username)
            messagebox.showinfo("Info", f"Mailing cycle for {username} paused!")
            self.update_account_table()

    def resume_account(self, username: str):
        account_state = self.account_manager.accounts.get(username)
        if account_state and account_state.is_active and account_state.is_paused:
            account_state.is_paused = False
            self.logger.info(f"Resumed mailing cycle for {username}", username)
            messagebox.showinfo("Info", f"Mailing cycle for {username} resumed!")
            self.update_account_table()
    
    def pause_selected_sessions(self):
        """Массовая пауза/снятие с паузы"""
        accounts = self.account_manager.load_accounts()
        selected = [acc["username"] for acc in accounts if self.selected_accounts.get(acc["username"], tk.BooleanVar()).get()]
        
        if not selected:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return
            
        count_paused = 0
        count_resumed = 0
        
        for username in selected:
            state = self.account_manager.accounts.get(username)
            if state and state.is_active and state.is_mailing:
                if not state.is_paused:
                    state.is_paused = True
                    count_paused += 1
                else:
                    state.is_paused = False
                    count_resumed += 1
        
        self.logger.info(f"Bulk action: Paused {count_paused}, Resumed {count_resumed}")
        self.update_account_table()
        messagebox.showinfo("Bulk Pause", f"Paused: {count_paused}\nResumed: {count_resumed}")

    def toggle_pause_single(self, username):
        state = self.account_manager.accounts.get(username)
        if state and state.is_active and state.is_mailing:
            state.is_paused = not state.is_paused # Переключаем True/False
            action = "Paused" if state.is_paused else "Resumed"
            self.logger.info(f"{action} mailing for {username}", username)
            self.update_account_table()
        else:
             pass

    def select_to_start(self):
        accounts = self.account_manager.load_accounts()
        selected = [acc for acc in accounts if self.selected_accounts.get(acc["username"], tk.BooleanVar()).get()]
        if not selected:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return
        confirm = messagebox.askyesno("Confirm", f"Start login for {len(selected)} account(s) with 15 seconds delay between each?")
        if not confirm:
            return
        threading.Thread(target=self.sequential_login, args=(selected,), daemon=True).start()
        messagebox.showinfo("Info", f"Starting login for {len(selected)} account(s). Check monitor for progress.")

    def start_mailing_for_ready(self):
        ready_accounts = []
        for username, state in self.account_manager.accounts.items():
            if state.is_active and not state.is_mailing and not state.need_relogin:
                has_groups = bool(state.groups) or bool(self.account_manager.load_saved_groups(username))
                if has_groups:
                    ready_accounts.append(username)
                    
        if not ready_accounts:
            messagebox.showwarning("Warning", "Нет готовых аккаунтов (нужен статус Active, наличие групп и отсутствие запущенной рассылки)!")
            return
            
        confirm = messagebox.askyesno("Confirm", f"Запустить рассылку для {len(ready_accounts)} готовых аккаунтов?")
        if confirm:
            for username in ready_accounts:
                self.task_scheduler.start_account_cycle(username)
            messagebox.showinfo("Success", f"Рассылка запущена для {len(ready_accounts)} аккаунтов!")
            self.update_account_table()

    def start_mailing_for_selected(self):
        accounts = self.account_manager.load_accounts()
        selected = [acc["username"] for acc in accounts if self.selected_accounts.get(acc["username"], tk.BooleanVar()).get()]
        
        if not selected:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return
            
        valid_count = 0
        for username in selected:
            state = self.account_manager.accounts.get(username)
            if state and state.is_active and not state.is_mailing:
                self.task_scheduler.start_account_cycle(username)
                valid_count += 1
                
        messagebox.showinfo("Info", f"Запущена рассылка для {valid_count} из {len(selected)} выбранных активных аккаунтов.")
        self.update_account_table()

    # --- AUTO PARSE LOGIC ---
    def start_auto_parse_selected(self):
        """Запускает кнопку Auto Parse"""
        accounts = self.account_manager.load_accounts()
        selected_usernames = [acc["username"] for acc in accounts if self.selected_accounts.get(acc["username"], tk.BooleanVar()).get()]
        
        # Фильтруем только активные (залогиненные) аккаунты
        active_selected = [u for u in selected_usernames if self.account_manager.accounts.get(u) and self.account_manager.accounts[u].is_active]

        if not active_selected:
            messagebox.showwarning(t("warning"), "No ACTIVE (logged in) accounts selected!")
            return

        confirm = messagebox.askyesno("Confirm", f"Start AUTO PARSING for {len(active_selected)} accounts?\nBatch size: 5.\nPopups will be disabled.")
        if not confirm:
            return

        # Запускаем в отдельном потоке, чтобы не вис интерфейс
        threading.Thread(target=self._auto_parse_worker, args=(active_selected,), daemon=True).start()

    def _auto_parse_worker(self, usernames):
        """Работает в фоне: делит на пачки по 5 и ждет выполнения"""
        batch_size = 5
        total = len(usernames)
        self.logger.info(f"--- STARTED AUTO PARSE: {total} accounts ---")

        for i in range(0, total, batch_size):
            batch = usernames[i : i + batch_size]
            self.logger.info(f"Processing batch {i//batch_size + 1}: {batch}")
            
            futures = []
            
            # Запускаем задачи для текущей пачки
            for username in batch:
                # Вызываем parse_groups_for с параметром silent=True
                future = asyncio.run_coroutine_threadsafe(
                    self.parse_groups_for(username, silent=True), 
                    self.loop
                )
                futures.append(future)
            
            # ЖДЕМ завершения всей пачки
            for f in futures:
                try:
                    f.result() # Этот метод блокирует поток, пока задача не выполнится
                except Exception as e:
                    self.logger.error(f"Error in auto parse batch: {e}")
            
            self.logger.info(f"Batch {i//batch_size + 1} finished.")
            # Небольшая пауза между пачками
            time.sleep(3)

        self.logger.info("--- AUTO PARSE COMPLETED ---")
        # Сообщение в конце всего процесса (одно общее)
        self.window.after(0, lambda: messagebox.showinfo("Done", "Auto Parsing Finished for all selected accounts!"))
    # ------------------------

    def open_bulk_edit_window(self):
        selected_usernames = [uname for uname, var in self.selected_accounts.items() if var.get()]
        if not selected_usernames:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return

        bulk_edit_win = ctk.CTkToplevel(self.window)
        bulk_edit_win.title(t("bulk_edit_title"))
        center_window(bulk_edit_win, 450, 450)
        bulk_edit_win.transient(self.window)
        bulk_edit_win.lift()
        bulk_edit_win.grab_set()

        ctk.CTkLabel(bulk_edit_win, text=t("editing_accounts").format(count=len(selected_usernames)), font=ctk.CTkFont(size=16, weight="bold")).pack(pady=15)

        group_frame = ctk.CTkFrame(bulk_edit_win)
        group_frame.pack(pady=10, padx=20, fill="x")

        chk_group_var = tk.BooleanVar(value=False)
        chk_group = ctk.CTkCheckBox(group_frame, text=t("change_group_chk"), variable=chk_group_var)
        chk_group.pack(anchor="w", padx=5, pady=(5,0))
        
        entry_group = ctk.CTkEntry(group_frame, placeholder_text=t("new_group_placeholder"))
        entry_group.pack(fill="x", padx=5, pady=(0,10))

        proxy_frame = ctk.CTkFrame(bulk_edit_win)
        proxy_frame.pack(pady=10, padx=20, fill="x")

        chk_proxy_var = tk.BooleanVar(value=False)
        chk_proxy = ctk.CTkCheckBox(proxy_frame, text=t("change_proxy_chk"), variable=chk_proxy_var)
        chk_proxy.pack(anchor="w", padx=5, pady=(5,0))

        ctk.CTkLabel(proxy_frame, text=t("proxy_help_text"), font=ctk.CTkFont(size=10)).pack(anchor="w", padx=5)
        txt_proxy = ctk.CTkTextbox(proxy_frame, height=120)
        txt_proxy.pack(fill="both", expand=True, padx=5, pady=(0,10))

        btn_apply = ctk.CTkButton(
            bulk_edit_win,
            text=t("apply_changes_btn"),
            command=lambda: self.apply_bulk_edits(
                selected_usernames,
                chk_group_var.get(), entry_group.get(),
                chk_proxy_var.get(), txt_proxy.get("1.0", "end-1c"),
                bulk_edit_win
            )
        )
        btn_apply.pack(pady=20)

    def apply_bulk_edits(self, usernames: List[str], should_change_group: bool, new_group: str, should_change_proxy: bool, proxies_text: str, window: ctk.CTkToplevel):
        if not should_change_group and not should_change_proxy:
            messagebox.showwarning(t("warning"), t("no_action_selected"))
            return

        accounts = self.account_manager.load_accounts()
        
        if should_change_proxy:
            proxies = [p.strip() for p in proxies_text.strip().splitlines() if p.strip()]
            if not proxies:
                messagebox.showerror(t("error"), t("proxy_field_empty"))
                return
            if len(proxies) != 1 and len(proxies) != len(usernames):
                message = t("proxy_count_mismatch").format(proxy_count=len(proxies), account_count=len(usernames))
                messagebox.showerror(t("error"), message)
                return

        for account in accounts:
            if account['username'] in usernames:
                if should_change_group:
                    account['group'] = new_group.strip()
                
                if should_change_proxy:
                    if len(proxies) == 1:
                        account['proxy'] = proxies[0]
                    else:
                        try:
                            proxy_index = usernames.index(account['username'])
                            account['proxy'] = proxies[proxy_index]
                        except (ValueError, IndexError):
                            self.logger.error(f"Could not find a proxy for {account['username']}")
        
        self.account_manager.save_accounts(accounts)
        messagebox.showinfo(t("success"), t("bulk_edit_success").format(count=len(usernames)))
        self.update_account_table()
        window.destroy()

    def sequential_login(self, accounts):
        total = len(accounts)
        success_count = 0
        error_count = 0
        error_accounts = []
        
        for index, account in enumerate(accounts):
            username = account["username"]
            try:
                self.logger.info(f"Starting login ({index + 1}/{total})", username)
                result = asyncio.run_coroutine_threadsafe(self.login_selected_account(account), self.loop).result(90)
                
                if result:
                    success_count += 1
                    self.logger.info(f"Login successful ({success_count}/{total})", username)
                else:
                    error_count += 1
                    error_accounts.append(username)
                    self.logger.warning(f"Login returned False", username)
                    
                self.update_account_table_threadsafe()
                
                if index < total - 1:
                    time.sleep(40)
                    
            except Exception as e:
                error_count += 1
                error_accounts.append(username)
                self.logger.error(f"Login failed: {str(e)}", username)
                # Продолжаем со следующим аккаунтом
                continue
        
        # Итоговый отчет
        if error_count > 0:
            self.logger.info(f"Login completed: {success_count} success, {error_count} errors. Failed: {', '.join(error_accounts)}")
        else:
            self.logger.info(f"Login completed: {success_count}/{total} accounts successfully logged in")

    async def login_selected_account(self, account):
        if not account:
            self.logger.error("No account selected for login")
            return False
        credentials = AccountCredentials(
            username=account["username"],
            password=account.get("password", ""),
            proxy=account.get("proxy"),
            user_agent=account.get("user_agent"),
            headless=account.get("headless", False),
            group=account.get("group", ""),
            auth_token=account.get("auth_token"),
            ct0_token=account.get("ct0_token")
        )
        if credentials.username in self.account_manager.accounts:
            state = self.account_manager.accounts[credentials.username]
            if state.is_active:
                self.logger.info(f"Account {credentials.username} is already active")
                return True
        try:
            self.logger.info("Beginning login process", credentials.username)
            await self.account_manager.login_account(credentials)
            state = self.account_manager.accounts.get(credentials.username)
            if state:
                saved_messages = self.message_manager.get_messages(credentials.username)
                state.mailing_messages = saved_messages
                state.cycle_settings = self.cycle_manager.get_cycle_settings(credentials.username)
                state.comment_settings = self.comment_manager.get_comment_settings(credentials.username) 
                state.media_enabled = state.cycle_settings.media_enabled
            self.logger.info("Login sucsessfull!", credentials.username)
            return True
        except Exception as e:
            err_msg = str(e)
            self.logger.error(f"Login failed: {err_msg}", credentials.username)
            self.window.after(0, lambda: messagebox.showerror("Error", f"{credentials.username}: {err_msg}"))
            return False

    def non_blocking_login(self, account):
        username = account["username"]
        self.logger.info("Starting login process...", username)
        threading.Thread(target=lambda: asyncio.run_coroutine_threadsafe(self.login_selected_account(account), self.loop).result(60), daemon=True).start()

    def non_blocking_parse(self, username):
        self.logger.info("Starting parse groups process...", username)
        threading.Thread(target=lambda: asyncio.run_coroutine_threadsafe(self.parse_groups_for(username, silent=False), self.loop).result(), daemon=True).start()

    async def parse_groups_for(self, username, silent=False):
        """
        silent=True используется для массового авто-парсинга, 
        чтобы не блокировать работу всплывающими окнами.
        """
        account_state = self.account_manager.accounts.get(username)
        if not account_state or not account_state.browser:
            if not silent:
                messagebox.showerror("Error", "Account must be logged in before parsing groups!")
            self.logger.error("Cannot parse groups: Account not logged in", username)
            return False
        try:
            # --- ВКЛЮЧАЕМ СТАТУС ---
            account_state.is_parsing = True 
            self.update_account_table_threadsafe() # Обновляем сразу
            
            self.logger.info("Starting to parse groups...", username)
            groups = await self.twitter_ops.find_groups(account_state.browser, username)
            if groups:
                account_state.groups = groups
                self.account_manager.save_groups()
                group_file = self.config.base_dir / f"groups_{username}.json"
                with open(group_file, 'w', encoding='utf-8') as f:
                    json.dump(list(groups), f, ensure_ascii=False, indent=4)
                
                # --- ВЫКЛЮЧАЕМ СТАТУС ---
                account_state.is_parsing = False
                self.update_account_table_threadsafe()
                
                self.logger.info(f"Successfully parsed {len(groups)} groups", username)
                
                if not silent:
                    messagebox.showinfo("Info", f"Found {len(groups)} groups for {username}!")
                return True
            else:
                account_state.is_parsing = False # Выключаем если пусто
                self.update_account_table_threadsafe()
                
                self.logger.warning("No groups found during parsing", username)
                if not silent:
                    messagebox.showwarning("Warning", f"No groups found for {username}")
                return False
        except Exception as e:
            account_state.is_parsing = False # Выключаем при ошибке
            self.update_account_table_threadsafe()
            
            err = f"Error parsing groups: {str(e)}"
            self.logger.error(err, username)
            if not silent:
                messagebox.showerror("Error", err)
            return False

    def clear_groups_for(self, username):
        account_state = self.account_manager.accounts.get(username)
        if account_state:
            account_state.groups.clear()
            self.account_manager.save_groups()
            messagebox.showinfo("Info", f"Groups cleared for {username}!")
            self.update_account_table()

    def non_blocking_mailing(self, username: str):
        account_state = self.account_manager.accounts.get(username)
        if not account_state or not account_state.browser:
            messagebox.showerror("Error", "Account must be logged in first!")
            return
        
        if not account_state.groups:
            account_state.groups = self.account_manager.load_saved_groups(username)
        if not account_state.mailing_messages:
            account_state.mailing_messages = self.message_manager.get_messages(username)

        # Группы теперь собираются автоматически в начале start_sending_cycle.
        if not account_state.mailing_messages:
            messagebox.showerror("Error", "No messages found! Please set messages in settings.")
            return

        if username in self.task_scheduler.running_tasks:
            messagebox.showinfo("Info", "Mailing is already running for this account.\nUse Pause/Resume to control it.")
            return

        account_state.is_mailing = True
        self.update_account_table()

        self.logger.info("Starting mailing process...", username)
        threading.Thread(target=lambda: self.mailing_for(username), daemon=True).start()

    def mailing_for(self, username):
        async def _mailing():
            try:
                account_state = self.account_manager.accounts.get(username)
                if not account_state or not account_state.browser:
                    self.window.after(0, lambda: messagebox.showerror("Error", "Account not logged in!"))
                    account_state.is_mailing = False
                    self.update_account_table_threadsafe()
                    return
                
                if not account_state.mailing_messages:
                    self.window.after(0, lambda: messagebox.showwarning("Warning", "No mailing messages set! Please configure them in settings."))
                    account_state.is_mailing = False
                    self.update_account_table_threadsafe()
                    return

                self.logger.info("Mailing start! Группы будут собраны автоматически из iChat.", username)
                self.task_scheduler.start_account_cycle(account_state, self.twitter_ops, self.account_manager, humanize=True)
            except Exception as e:
                self.logger.error(f"Error in mailing_for: {str(e)}", username)
                # Make sure to reset is_mailing flag on error
                account_state = self.account_manager.accounts.get(username)
                if account_state:
                    account_state.is_mailing = False
                    self.update_account_table_threadsafe()
        
        try:
            return asyncio.run_coroutine_threadsafe(_mailing(), self.loop)
        except Exception as e:
            self.logger.error(f"Error starting mailing thread: {str(e)}", username)
            return None

    def auto_refresh_loop(self):
        """Run automatic refresh in background (smart update)"""
        if self._stop_auto_refresh:
            return
            
        self.check_all_browsers()  # Проверяем статус всех браузеров
        self.update_account_table()
        # Call itself after 1500 ms (1.5 sec)
        after_id = self.window.after(1500, self.auto_refresh_loop)
        self._after_ids.append(after_id)
    
    def check_all_browsers(self):
        """Проверяет все активные браузеры и помечает как inactive если закрыты"""
        for username, state in self.account_manager.accounts.items():
            if state.is_active and state.browser:
                try:
                    # Пытаемся получить текущий URL или заголовок окна
                    # Если браузер закрыт, это вызовет исключение
                    _ = state.browser.current_window_handle
                    # Дополнительная проверка - пробуем выполнить простую команду
                    state.browser.title  # Это не выполняет запрос, просто читает заголовок
                except Exception:
                    # Браузер был закрыт вручную
                    self.logger.info(f"Browser closed manually for {username}, marking as inactive")
                    state.is_active = False
                    state.is_mailing = False
                    state.browser = None

    def update_account_table(self):
        """Подготовка данных и вызов отрисовки виртуальной таблицы."""
        # 1. Получаем свежие данные из менеджера (это быстро, т.к. кэшировано)
        raw_rows = self.account_manager.get_table_data()
        
        # 2. Фильтрация
        selected_group = self.group_filter_var.get()
        
        # Обновляем выпадающий список групп
        all_groups = sorted(list(set(r["account"].get("group", "") for r in raw_rows if r["account"].get("group"))))
        new_values = ["All Accounts"] + all_groups
        if self.group_filter_menu.cget("values") != new_values:
            self.group_filter_menu.configure(values=new_values)

        if selected_group == "All Accounts":
            self.filtered_accounts = raw_rows
        else:
            self.filtered_accounts = [r for r in raw_rows if r["account"].get("group", "") == selected_group]

        # 3. Синхронизация выбора (если добавились новые аккаунты, создаем для них переменные выбора)
        for row in self.filtered_accounts:
            uname = row["username"]
            if uname not in self.selected_accounts:
                self.selected_accounts[uname] = tk.BooleanVar(value=False)

        # 4. Обновление скроллбара и отрисовка
        self._update_scrollbar_size()
        self.render_virtual_table()

    def setup_account_table(self):
        self.selected_accounts = {}
        
        # Основной контейнер таблицы
        self.table_frame = ctk.CTkFrame(self.window)
        self.table_frame.pack(pady=10, padx=20, fill="both", expand=True)

        # --- ЗАГОЛОВОК ---
        header_frame = ctk.CTkFrame(self.table_frame, height=30)
        header_frame.pack(fill="x", padx=2, pady=2)
        
        self.col_names = [
            "Select All", "Status", "#", "@Username", "Groups", "Last Launch",
            t("login"), "View", t("parse"), t("mailing"), t("edit"), t("settings"), t("comments"),
            "Pause/Res", "Stat", t("close"), t("delete")
        ]
        # Исправленные ширины (Pause/Res вместо S/R)
        self.col_widths = [80, 80, 30, 150, 50, 80, 60, 40, 60, 60, 50, 70, 50, 70, 50, 60, 60]

        self.select_all_var = tk.BooleanVar()
        select_all_chk = ctk.CTkCheckBox(
            header_frame, 
            variable=self.select_all_var, 
            text="", 
            width=self.col_widths[0], 
            command=self.toggle_select_all
        )
        select_all_chk.pack(side="left", padx=2)

        for i, name in enumerate(self.col_names[1:]): 
            lbl = ctk.CTkLabel(header_frame, text=name, width=self.col_widths[i+1], anchor="w", font=ctk.CTkFont(weight="bold"))
            lbl.pack(side="left", padx=2)

        # --- ТЕЛО ТАБЛИЦЫ (БЕЗ CANVAS) ---
        body_container = ctk.CTkFrame(self.table_frame)
        body_container.pack(fill="both", expand=True)

        # Скроллбар справа
        self.v_scrollbar = ctk.CTkScrollbar(body_container, command=self._scrollbar_command)
        self.v_scrollbar.pack(side="right", fill="y")

        # Фрейм для строк
        self.rows_container = ctk.CTkFrame(body_container, fg_color="transparent")
        self.rows_container.pack(side="left", fill="both", expand=True)
        
        # Привязка колесика мыши
        self.rows_container.bind("<MouseWheel>", self._on_mouse_wheel) # Windows
        self.rows_container.bind("<Button-4>", self._on_mouse_wheel)   # Linux up
        self.rows_container.bind("<Button-5>", self._on_mouse_wheel)   # Linux down

        # --- СОЗДАНИЕ ПУЛА ВИДЖЕТОВ (1 раз при запуске) ---
        self._create_row_pool()

    def _create_row_pool(self):
        """Создает фиксированное количество строк, которые мы будем обновлять."""
        self.row_pool = []
        
        for i in range(self.visible_rows_count):
            row_frame = ctk.CTkFrame(self.rows_container, height=35)
            row_frame.pack(fill="x", pady=1)
            
            # Пробрасываем событие скролла на фрейм строки, чтобы колесико работало везде
            row_frame.bind("<MouseWheel>", self._on_mouse_wheel)
            
            widgets = {}
            
            # 0. Checkbox (хитрый трюк: мы не привязываем variable, а управляем состоянием вручную)
            chk = ctk.CTkCheckBox(row_frame, text="", width=self.col_widths[0], command=lambda idx=i: self._on_row_checkbox_click(idx))
            chk.pack(side="left", padx=2)
            widgets["chk"] = chk
            
            # 1. Status
            lbl_status = ctk.CTkLabel(row_frame, text="", width=self.col_widths[1])
            lbl_status.pack(side="left", padx=2)
            widgets["status"] = lbl_status
            
            # 2. Index
            lbl_idx = ctk.CTkLabel(row_frame, text="", width=self.col_widths[2])
            lbl_idx.pack(side="left")
            widgets["idx"] = lbl_idx
            
            # 3. Username
            lbl_user = ctk.CTkLabel(row_frame, text="", width=self.col_widths[3], anchor="w")
            lbl_user.pack(side="left", padx=2)
            widgets["user"] = lbl_user
            
            # 4. Groups
            lbl_grp = ctk.CTkLabel(row_frame, text="", width=self.col_widths[4])
            lbl_grp.pack(side="left", padx=2)
            widgets["grp"] = lbl_grp
            
            # 5. Last Launch
            lbl_last = ctk.CTkLabel(row_frame, text="", width=self.col_widths[5], anchor="w")
            lbl_last.pack(side="left", padx=2)
            widgets["last"] = lbl_last
            
            # Кнопки (сохраняем ссылки на сами кнопки, чтобы менять configure(command=...))
            # Для компактности кода создания кнопок:
            btns_config = [
                ("login", t("login"), self.col_widths[6]),
                ("view", "👀", self.col_widths[7]),
                ("parse", t("parse"), self.col_widths[8]),
                ("mailing", t("mailing"), self.col_widths[9]),
                ("edit", t("edit"), self.col_widths[10]),
                ("settings", t("settings"), self.col_widths[11]),
                ("comm", "💬", self.col_widths[12]),
                
                # Заменили S/R на Pause Toggle
                ("pause_toggle", "Pause", self.col_widths[13]),
                
                ("stat", "Stat", self.col_widths[14]),
                ("close", t("close"), self.col_widths[15]),
                ("del", t("delete"), self.col_widths[16]),
            ]
            
            for key, text, width in btns_config:
                btn = ctk.CTkButton(row_frame, text=text, width=width)
                btn.pack(side="left", padx=2)
                widgets[key] = btn
                # Привязываем скролл к кнопкам тоже, если мышь над ними
                btn.bind("<MouseWheel>", self._on_mouse_wheel)

            self.row_pool.append({"frame": row_frame, "widgets": widgets})

    def _update_scrollbar_size(self):
        """Обновляет размер ползунка скроллбара в зависимости от кол-ва данных."""
        total = len(self.filtered_accounts)
        if total <= self.visible_rows_count:
            self.v_scrollbar.set(0, 1) # Скрываем или делаем полным, если данных мало
        else:
            # Размер ползунка пропорционален видимой части
            step = self.visible_rows_count / total
            # Текущая позиция
            start = self.scroll_start_index / total
            end = start + step
            self.v_scrollbar.set(start, min(1.0, end))

    def _scrollbar_command(self, command, *args):
        """Обработка перетаскивания скроллбара."""
        total = len(self.filtered_accounts)
        if command == 'moveto':
            fraction = float(args[0])
            self.scroll_start_index = int(fraction * total)
        elif command == 'scroll':
            # args[0] = number, args[1] = 'units' or 'pages'
            amount = int(args[0])
            self.scroll_start_index += amount
            
        # Ограничиваем границы
        max_start = max(0, total - self.visible_rows_count)
        self.scroll_start_index = max(0, min(self.scroll_start_index, max_start))
        
        self._update_scrollbar_size()
        self.render_virtual_table()

    def _on_mouse_wheel(self, event):
        """Обработка колесика мыши."""
        if len(self.filtered_accounts) <= self.visible_rows_count:
            return

        if event.num == 5 or event.delta < 0:  # Вниз
            self.scroll_start_index += 1
        elif event.num == 4 or event.delta > 0:  # Вверх
            self.scroll_start_index -= 1
            
        # Проверка границ
        max_start = max(0, len(self.filtered_accounts) - self.visible_rows_count)
        self.scroll_start_index = max(0, min(self.scroll_start_index, max_start))
        
        self._update_scrollbar_size()
        self.render_virtual_table()

    def _on_row_checkbox_click(self, row_pool_index):
        """Обработка клика по чекбоксу в виртуальной строке."""
        # Вычисляем реальный индекс данных
        data_index = self.scroll_start_index + row_pool_index
        if 0 <= data_index < len(self.filtered_accounts):
            username = self.filtered_accounts[data_index]["username"]
            # Инвертируем значение
            current_val = self.selected_accounts[username].get()
            self.selected_accounts[username].set(not current_val)
            # Принудительно обновляем виджет чекбокса, т.к. он не привязан через variable
            if not current_val:
                self.row_pool[row_pool_index]["widgets"]["chk"].select()
            else:
                self.row_pool[row_pool_index]["widgets"]["chk"].deselect()

    def render_virtual_table(self):
        """ГЛАВНЫЙ МЕТОД: Заполняет пул строк данными."""
        
        for i in range(self.visible_rows_count):
            row_widgets = self.row_pool[i]
            frame = row_widgets["frame"]
            w = row_widgets["widgets"]
            
            data_index = self.scroll_start_index + i
            
            # Если данных нет (конец списка), скрываем строку
            if data_index >= len(self.filtered_accounts):
                frame.pack_forget()
                continue
            
            # Если строка была скрыта, показываем
            frame.pack(fill="x", pady=1)
            
            # Получаем данные
            row_data = self.filtered_accounts[data_index]
            account = row_data["account"]
            username = row_data["username"]
            
            # --- ОБНОВЛЕНИЕ ТЕКСТА И ЦВЕТОВ ---
            
            # Checkbox: вручную ставим состояние
            is_selected = self.selected_accounts.get(username, tk.BooleanVar(value=False)).get()
            if is_selected: w["chk"].select()
            else: w["chk"].deselect()
            
            # Status (Dirty check встроен в .configure, но для скорости можно проверить)
            w["status"].configure(text=row_data["status_text"], text_color=row_data["status_color"])
            
            w["idx"].configure(text=str(data_index + 1))
            w["user"].configure(text=username)
            w["grp"].configure(text=str(row_data["groups_count"]))
            w["last"].configure(text=row_data["last_launch"])
            
            # Логика для кнопки Паузы
            account_state = self.account_manager.accounts.get(username)
            pause_text = "Pause"
            pause_color = "#3B8ED0" # Стандартный синий
            
            if account_state and account_state.is_paused:
                pause_text = "▶ Resume"
                pause_color = "#27ae60" # Зеленый
            elif not account_state or not account_state.is_mailing:
                pause_text = "Wait" # Или Disable, если рассылка не идет
                pause_color = "gray"

            w["pause_toggle"].configure(text=pause_text, fg_color=pause_color, 
                                        command=lambda u=username: self.toggle_pause_single(u))

            # --- ОБНОВЛЕНИЕ КОМАНД КНОПОК ---
            # Используем lambda с дефолтными аргументами, чтобы захватить текущие значения
            
            w["login"].configure(command=lambda a=account: self.non_blocking_login(a))
            w["view"].configure(command=lambda u=username: self.bring_browser_to_front(u))
            w["parse"].configure(command=lambda u=username: self.non_blocking_parse(u))
            w["mailing"].configure(command=lambda u=username: self.non_blocking_mailing(u))
            w["edit"].configure(command=lambda a=account: self.open_edit_window(a))
            w["settings"].configure(command=lambda a=account: self.open_settings_window(a))
            w["comm"].configure(command=lambda a=account: self.open_comment_settings_window(a))
            
            # Pause toggle выше уже настроен с command
            
            w["stat"].configure(command=lambda u=username: self.show_daily_stats(u))
            w["close"].configure(command=lambda u=username: self.close_account(u))
            w["del"].configure(command=lambda a=account: self.delete_account(a))

    def toggle_select_all(self):
        new_state = self.select_all_var.get()
        for acc in self.filtered_accounts:
            username = acc.get("username")
            if username in self.selected_accounts:
                self.selected_accounts[username].set(new_state)
        # Принудительно перерисовываем, чтобы галочки обновились визуально
        self.render_virtual_table()

    def update_scrollregion(self, event):
        # Obsolete with virtualization
        pass

    def bring_browser_to_front(self, username: str):
        """Выводит окно браузера на передний план без разворачивания на весь экран"""
        account_state = self.account_manager.accounts.get(username)
        if account_state and account_state.browser:
            try:
                # 1. Получаем текущие размеры и положение окна
                try:
                    rect = account_state.browser.get_window_rect()
                    # Проверка на случай, если окно уже свернуто (Windows иногда выдает координаты -32000)
                    if rect['x'] < -1000 or rect['y'] < -1000:
                        rect = {'x': 50, 'y': 50, 'width': 1050, 'height': 800}
                except Exception:
                    # Если не удалось получить, берем дефолтные
                    rect = {'x': 50, 'y': 50, 'width': 1050, 'height': 800}

                # 2. Сворачиваем окно (триггер для системы)
                account_state.browser.minimize_window()

                # 3. Функция восстановления (вместо maximize_window используем set_window_rect)
                def restore_original_size():
                    try:
                        account_state.browser.set_window_rect(
                            x=rect['x'], 
                            y=rect['y'], 
                            width=rect['width'], 
                            height=rect['height']
                        )
                        # Переключаем фокус на окно
                        account_state.browser.switch_to.window(account_state.browser.current_window_handle)
                    except Exception as e:
                        print(f"Error restoring window: {e}")

                # 4. Выполняем через 200мс (даем время на анимацию сворачивания)
                self.window.after(200, restore_original_size)

            except Exception as e:
                self.logger.error(f"Could not bring browser to front: {e}", username)
        else:
            messagebox.showwarning("Warning", f"Browser for {username} is not open!")

    def show_daily_stats(self, username: str):
        count = self.stats_manager.get_stats_for_24h(username)
        account_state = self.account_manager.accounts.get(username)
        comments = account_state.comments_sent_24h if account_state else 0
        
        messagebox.showinfo(
            "24-Hour Stats",
            f"Account @{username}:\nMessages: {count}\nComments today: {comments}"
        )

    def delete_account(self, account_to_delete):
        confirm = messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the account: {account_to_delete['username']}?")
        if confirm:
            self.task_scheduler.stop_account_cycle(account_to_delete['username'])
            accounts = self.account_manager.load_accounts()
            updated_accounts = [acc for acc in accounts if acc.get('username') != account_to_delete.get('username')]
            self.account_manager.save_accounts(updated_accounts)
            
            if account_to_delete['username'] in self.account_manager.accounts:
                del self.account_manager.accounts[account_to_delete['username']]
            
            if account_to_delete['username'] in self.selected_accounts:
                del self.selected_accounts[account_to_delete['username']]
            
            # Синхронизируем с БД Telegram бота
            if hasattr(self, 'telegram_bot_instance') and self.telegram_bot_instance:
                self.telegram_bot_instance.sync_local_to_db()
            
            # Обновляем таблицу, чтобы список сдвинулся
            self.update_account_table()

            messagebox.showinfo("Success", f"Account {account_to_delete['username']} has been deleted.")

    def delete_selected_accounts(self):
        """Удаляет все выбранные (отмеченные чекбоксом) аккаунты"""
        selected_usernames = [uname for uname, var in self.selected_accounts.items() if var.get()]
        
        if not selected_usernames:
            messagebox.showwarning("No Selection", "No accounts selected for deletion.")
            return
        
        confirm = messagebox.askyesno(
            "Confirm Mass Deletion", 
            f"Are you sure you want to delete {len(selected_usernames)} selected account(s)?\n\n" + 
            "\n".join(selected_usernames[:10]) + 
            ("\n..." if len(selected_usernames) > 10 else "")
        )
        
        if not confirm:
            return
        
        accounts = self.account_manager.load_accounts()
        
        for username in selected_usernames:
            # Останавливаем задачи
            self.task_scheduler.stop_account_cycle(username)
            
            # Удаляем из памяти
            if username in self.account_manager.accounts:
                del self.account_manager.accounts[username]
            
            if username in self.selected_accounts:
                del self.selected_accounts[username]
        
        # Обновляем файл accounts.json
        updated_accounts = [acc for acc in accounts if acc.get('username') not in selected_usernames]
        self.account_manager.save_accounts(updated_accounts)
        
        # Синхронизируем с БД Telegram бота
        if hasattr(self, 'telegram_bot_instance') and self.telegram_bot_instance:
            self.telegram_bot_instance.sync_local_to_db()
        
        # Обновляем таблицу
        self.update_account_table()
        
        messagebox.showinfo("Success", f"{len(selected_usernames)} account(s) deleted successfully.")

    def open_monitor_window(self):
        if hasattr(self, "monitor_window") and self.monitor_window.window.winfo_exists():
            self.monitor_window.window.deiconify()
        else:
            self.monitor_window = MonitorWindow(self.window, self.logger, self.account_manager)
        self.update_monitor()

    def update_monitor(self):
        if hasattr(self, "monitor_window") and self.monitor_window.window.winfo_exists():
            self.monitor_window.update_monitor()

    def open_add_account_window(self):
        add_win = ctk.CTkToplevel(self.window)
        add_win.title(t("add_account"))
        center_window(add_win, 425, 720)
        add_win.transient(self.window)
        add_win.lift()
        
        tk.Label(add_win, text="Username:").pack(pady=5)
        username_entry = ctk.CTkEntry(add_win, width=300)
        username_entry.pack(pady=5, padx=20)
        
        tk.Label(add_win, text="Password:").pack(pady=5)
        password_entry = ctk.CTkEntry(add_win, show="*", width=300)
        password_entry.pack(pady=5, padx=20)
        
        tk.Label(add_win, text="Proxy (optional):").pack(pady=5)
        proxy_entry = ctk.CTkEntry(add_win, width=300)
        proxy_entry.pack(pady=5, padx=20)
        
        tk.Label(add_win, text="User-Agent (optional):").pack(pady=5)
        ua_entry = ctk.CTkEntry(add_win, width=300)
        ua_entry.pack(pady=5, padx=20)

        tk.Label(add_win, text="Group (optional):").pack(pady=5)
        group_entry = ctk.CTkEntry(add_win, width=300)
        group_entry.pack(pady=5, padx=20)
        
        # Auth Token fields
        tk.Label(add_win, text="Auth Token (optional):").pack(pady=5)
        auth_token_entry = ctk.CTkEntry(add_win, width=300)
        auth_token_entry.pack(pady=5, padx=20)
        
        tk.Label(add_win, text="CT0 Token (optional):").pack(pady=5)
        ct0_token_entry = ctk.CTkEntry(add_win, width=300)
        ct0_token_entry.pack(pady=5, padx=20)
        
        # Headless checkbox removed
        
        def add_and_close():
            username = username_entry.get().strip()
            password = password_entry.get().strip()
            auth_token = auth_token_entry.get().strip()
            ct0_token = ct0_token_entry.get().strip()
            
            if not username:
                messagebox.showwarning("Warning", "Username is required!")
                return
            
            if not password and not auth_token:
                messagebox.showwarning("Warning", "Password or Auth Token is required!")
                return
            
            acs = self.account_manager.load_accounts()
            if any(acc['username'] == username for acc in acs):
                 messagebox.showwarning("Warning", f"Account with username '{username}' already exists!")
                 return

            acs.append({
                "username": username,
                "password": password,
                "proxy": proxy_entry.get().strip(),
                "user_agent": ua_entry.get().strip(),
                "group": group_entry.get().strip(),
                "auth_token": auth_token,
                "ct0_token": ct0_token,
                "headless": False # Always false now
            })
            self.account_manager.save_accounts(acs)
            # The background worker will pick this up, 
            # and the auto_refresh_loop will draw it.
            add_win.destroy()
            
        add_btn = ctk.CTkButton(add_win, text=t("add_account"), command=add_and_close, font=ctk.CTkFont(size=14))
        add_btn.pack(pady=10)

    def open_import_accounts_window(self):
        """Open window for importing accounts from text format"""
        import_win = ctk.CTkToplevel(self.window)
        import_win.title("Import Accounts")
        center_window(import_win, 500, 450)
        import_win.transient(self.window)
        import_win.lift()
        
        ctk.CTkLabel(import_win, text="Import Accounts", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(import_win, text="Format: username|auth_token|ct0_token|proxy|group", font=ctk.CTkFont(size=12)).pack(pady=5)
        ctk.CTkLabel(import_win, text="One account per line. auth_token is required.", font=ctk.CTkFont(size=10), text_color="gray").pack(pady=5)
        
        def load_from_file():
            from tkinter import filedialog
            file_path = filedialog.askopenfilename(title="Select accounts file", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
            if file_path:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        accounts_text.insert("1.0", content)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to read file: {e}", parent=import_win)
        
        file_btn = ctk.CTkButton(import_win, text="📂 Load from File", command=load_from_file)
        file_btn.pack(pady=5)
        
        text_frame = ctk.CTkFrame(import_win)
        text_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        accounts_text = ctk.CTkTextbox(text_frame, height=200)
        accounts_text.pack(fill="both", expand=True, padx=10, pady=10)
        
        def import_accounts():
            text = accounts_text.get("1.0", "end-1c").strip()
            if not text:
                messagebox.showwarning("Warning", "Please enter account data!", parent=import_win)
                return
            
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            acs = self.account_manager.load_accounts()
            existing_users = {acc['username'] for acc in acs}
            added_count = 0
            skipped_count = 0
            
            for line in lines:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) < 2:
                    skipped_count += 1
                    continue
                
                username = parts[0]
                auth_token = parts[1]
                ct0_token = parts[2] if len(parts) > 2 else ""
                proxy = parts[3] if len(parts) > 3 else ""
                group = parts[4] if len(parts) > 4 else ""
                
                if not username or not auth_token or username in existing_users:
                    skipped_count += 1
                    continue
                
                new_account = {
                    "username": username,
                    "password": "",
                    "proxy": proxy,
                    "user_agent": "",
                    "group": group,
                    "auth_token": auth_token,
                    "ct0_token": ct0_token,
                    "headless": False
                }
                
                acs.append(new_account)
                existing_users.add(username)
                added_count += 1
            
            self.account_manager.save_accounts(acs)
            messagebox.showinfo("Import Complete", f"Successfully added {added_count} accounts.\nSkipped: {skipped_count}", parent=import_win)
            import_win.destroy()
        
        import_btn = ctk.CTkButton(import_win, text="Import", command=import_accounts, font=ctk.CTkFont(size=14))
        import_btn.pack(pady=10)

    def open_edit_window(self, account):
        original_username = account["username"]
        edit_win = ctk.CTkToplevel(self.window)
        edit_win.title("Edit Account")
        center_window(edit_win, 415, 720)
        edit_win.transient(self.window)
        edit_win.lift()
        
        ctk.CTkLabel(edit_win, text="Edit Account Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=15)
        input_frame = ctk.CTkFrame(edit_win)
        input_frame.pack(padx=20, pady=10, fill="x")
        
        ctk.CTkLabel(input_frame, text="Username:", font=ctk.CTkFont(size=12)).pack(pady=5)
        username_entry = ctk.CTkEntry(input_frame, width=300, font=ctk.CTkFont(size=12))
        username_entry.insert(0, account.get("username", ""))
        username_entry.pack(pady=(0, 10))
        
        ctk.CTkLabel(input_frame, text="Password:", font=ctk.CTkFont(size=12)).pack(pady=5)
        password_entry = ctk.CTkEntry(input_frame, width=300, show="*", font=ctk.CTkFont(size=12))
        password_entry.insert(0, account.get("password", ""))
        password_entry.pack(pady=(0, 10))
        
        ctk.CTkLabel(input_frame, text="Proxy:", font=ctk.CTkFont(size=12)).pack(pady=5)
        proxy_entry = ctk.CTkEntry(input_frame, width=300, font=ctk.CTkFont(size=12))
        proxy_entry.insert(0, account.get("proxy", ""))
        proxy_entry.pack(pady=(0, 10))
        
        ctk.CTkLabel(input_frame, text="User-Agent:", font=ctk.CTkFont(size=12)).pack(pady=5)
        ua_entry = ctk.CTkEntry(input_frame, width=300, font=ctk.CTkFont(size=12))
        ua_entry.insert(0, account.get("user_agent", ""))
        ua_entry.pack(pady=(0, 10))

        ctk.CTkLabel(input_frame, text="Group:", font=ctk.CTkFont(size=12)).pack(pady=5)
        group_entry = ctk.CTkEntry(input_frame, width=300, font=ctk.CTkFont(size=12))
        group_entry.insert(0, account.get("group", ""))
        group_entry.pack(pady=(0, 10))
        
        # Auth Token fields
        ctk.CTkLabel(input_frame, text="Auth Token:", font=ctk.CTkFont(size=12)).pack(pady=5)
        auth_token_entry = ctk.CTkEntry(input_frame, width=300, font=ctk.CTkFont(size=12))
        if account.get("auth_token"):
            auth_token_entry.insert(0, str(account.get("auth_token", "")))
        auth_token_entry.pack(pady=(0, 10))
        
        ctk.CTkLabel(input_frame, text="CT0 Token:", font=ctk.CTkFont(size=12)).pack(pady=5)
        ct0_token_entry = ctk.CTkEntry(input_frame, width=300, font=ctk.CTkFont(size=12))
        if account.get("ct0_token"):
            ct0_token_entry.insert(0, str(account.get("ct0_token", "")))
        ct0_token_entry.pack(pady=(0, 10))
        
        # Headless checkbox removed
        
        def save_edits():
            new_username = username_entry.get().strip()
            if not new_username:
                messagebox.showwarning("Warning", "Username cannot be empty!")
                return

            acs = self.account_manager.load_accounts()
            if new_username != original_username and any(a['username'] == new_username for a in acs):
                messagebox.showwarning("Warning", f"Username '{new_username}' is already taken!")
                return
            
            for idx, a in enumerate(acs):
                if a["username"] == original_username:
                    acs[idx]["username"] = new_username
                    acs[idx]["password"] = password_entry.get()
                    acs[idx]["proxy"] = proxy_entry.get().strip()
                    acs[idx]["user_agent"] = ua_entry.get().strip()
                    acs[idx]["group"] = group_entry.get().strip()
                    acs[idx]["auth_token"] = auth_token_entry.get().strip()
                    acs[idx]["ct0_token"] = ct0_token_entry.get().strip()
                    acs[idx]["headless"] = False # Always false
                    break
            
            self.account_manager.save_accounts(acs)
            
            if new_username != original_username and original_username in self.account_manager.accounts:
                self.account_manager.accounts[new_username] = self.account_manager.accounts.pop(original_username)
                self.account_manager.accounts[new_username].username = new_username
                
                # Update widget map key (not strictly needed with virtual table, but good practice)
                pass

            edit_win.destroy()
            # Messagebox removed
            self.update_account_table()
            
        ctk.CTkButton(edit_win, text=t("save_changes"), command=save_edits, font=ctk.CTkFont(size=14), width=200).pack(pady=20)

    # --- NEW WINDOW FOR COMMENT SETTINGS ---
    def open_comment_settings_window(self, account):
        username = account["username"]
        win = ctk.CTkToplevel(self.window)
        win.title(f"Comments - {username}")
        center_window(win, 500, 450)
        win.transient(self.window)
        win.grab_set()

        current_settings = self.comment_manager.get_comment_settings(username)

        enable_var = tk.BooleanVar(value=current_settings.enabled)
        ctk.CTkSwitch(win, text="Enable Comments", variable=enable_var).pack(pady=10)

        ctk.CTkLabel(win, text="Targets File (Usernames):").pack(pady=(10,0))
        frame_targets = ctk.CTkFrame(win)
        frame_targets.pack(fill="x", padx=20)
        entry_targets = ctk.CTkEntry(frame_targets)
        entry_targets.insert(0, current_settings.targets_file)
        entry_targets.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        def browse_targets():
            f = fd.askopenfilename(filetypes=[("Text Files", "*.txt")])
            if f:
                entry_targets.delete(0, "end")
                entry_targets.insert(0, f)
        ctk.CTkButton(frame_targets, text="...", width=30, command=browse_targets).pack(side="right", padx=5)

        ctk.CTkLabel(win, text="Comments Text File:").pack(pady=(10,0))
        frame_comments = ctk.CTkFrame(win)
        frame_comments.pack(fill="x", padx=20)
        entry_comments = ctk.CTkEntry(frame_comments)
        entry_comments.insert(0, current_settings.comments_file)
        entry_comments.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        def browse_comments():
            f = fd.askopenfilename(filetypes=[("Text Files", "*.txt")])
            if f:
                entry_comments.delete(0, "end")
                entry_comments.insert(0, f)
        ctk.CTkButton(frame_comments, text="...", width=30, command=browse_comments).pack(side="right", padx=5)

        ctk.CTkLabel(win, text="Photo Folder (Random Image):").pack(pady=(10,0))
        frame_photo = ctk.CTkFrame(win)
        frame_photo.pack(fill="x", padx=20)
        entry_photo = ctk.CTkEntry(frame_photo)
        entry_photo.insert(0, current_settings.photo_path)
        entry_photo.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        
        def browse_photo():
            # ИЗМЕНЕНО: Выбор папки, а не файла
            d = fd.askdirectory()
            if d:
                entry_photo.delete(0, "end")
                entry_photo.insert(0, d)
                
        ctk.CTkButton(frame_photo, text="...", width=30, command=browse_photo).pack(side="right", padx=5)

        ctk.CTkLabel(win, text="Daily Limit (24h):").pack(pady=(10,0))
        entry_limit = ctk.CTkEntry(win, width=100)
        entry_limit.insert(0, str(current_settings.daily_limit))
        entry_limit.pack(pady=5)

        def save():
            new_s = CommentSettings(
                enabled=enable_var.get(),
                targets_file=entry_targets.get().strip(),
                comments_file=entry_comments.get().strip(),
                photo_path=entry_photo.get().strip(),
                daily_limit=int(entry_limit.get() or 0)
            )
            self.comment_manager.save_comment_settings(username, new_s)
            
            if username in self.account_manager.accounts:
                self.account_manager.accounts[username].comment_settings = new_s

            # Messagebox removed
            win.destroy()

        ctk.CTkButton(win, text="Save", command=save).pack(pady=20)

    def open_mass_message_edit_window(self):
        selected_usernames = [uname for uname, var in self.selected_accounts.items() if var.get()]
        if not selected_usernames:
            messagebox.showwarning(t("warning"), t("no_accounts_selected"))
            return

        template_user = selected_usernames[0]
        
        # Загружаем ТОЛЬКО настройки таймингов из первого аккаунта (как шаблон)
        loaded_cycle = self.cycle_manager.get_cycle_settings(template_user)
        
        # ВАЖНО: Список сообщений делаем ПУСТЫМ.
        # Чтобы при добавлении (Append) мы не копировали чужие старые сообщения.
        loaded_messages = [{"text": "", "count": 1}]

        settings_win = ctk.CTkToplevel(self.window)
        settings_win.title(f"Mass Edit ({len(selected_usernames)} accounts)")
        center_window(settings_win, 760, 700)
        settings_win.transient(self.window)
        settings_win.lift()
        settings_win.grab_set()

        # --- ЧЕКБОКСЫ (ЧТО ОБНОВЛЯТЬ) ---
        chk_frame = ctk.CTkFrame(settings_win, fg_color="transparent")
        chk_frame.pack(pady=(15, 5))
        
        var_update_settings = tk.BooleanVar(value=True)
        var_update_messages = tk.BooleanVar(value=True)

        chk_settings = ctk.CTkCheckBox(chk_frame, text="✅ Update Settings (Timings)", variable=var_update_settings, font=ctk.CTkFont(weight="bold"))
        chk_settings.pack(side="left", padx=20)
        
        chk_messages = ctk.CTkCheckBox(chk_frame, text="✅ Update Messages", variable=var_update_messages, font=ctk.CTkFont(weight="bold"))
        chk_messages.pack(side="left", padx=20)

        info_label = ctk.CTkLabel(
            settings_win, 
            text=f"Editing {len(selected_usernames)} accounts.\nTimings loaded from @{template_user}. Message list is clean.", 
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        info_label.pack(pady=(5, 5))

        # --- НАСТРОЙКИ ЦИКЛА ---
        lbl_cycle = ctk.CTkLabel(settings_win, text=f"⚙️ {t('msg_cycle')}", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_cycle.pack(pady=5)
        
        frm_cycle = ctk.CTkFrame(settings_win)
        frm_cycle.pack(pady=5, padx=20, fill="x")
        
        ctk.CTkLabel(frm_cycle, text=f"{t('msg_cycle')}:").pack(side="left", padx=5)
        entry_messages = ctk.CTkEntry(frm_cycle, width=50)
        entry_messages.insert(0, str(loaded_cycle.messages_per_cycle))
        entry_messages.pack(side="left", padx=5)
        
        ctk.CTkLabel(frm_cycle, text=f"{t('rt_count')}:").pack(side="left", padx=5)
        entry_retweet_count = ctk.CTkEntry(frm_cycle, width=50)
        entry_retweet_count.insert(0, str(loaded_cycle.retweet_count))
        entry_retweet_count.pack(side="left", padx=5)
        
        ctk.CTkLabel(frm_cycle, text=f"{t('rest_time')}:").pack(side="left", padx=5)
        entry_rest = ctk.CTkEntry(frm_cycle, width=50)
        entry_rest.insert(0, str(loaded_cycle.rest_time_minutes))
        entry_rest.pack(side="left", padx=5)
        
        ctk.CTkLabel(frm_cycle, text="RT Limit (24h):").pack(side="left", padx=5)
        entry_max_retweets = ctk.CTkEntry(frm_cycle, width=50)
        entry_max_retweets.insert(0, str(loaded_cycle.max_total_retweets))
        entry_max_retweets.pack(side="left", padx=5)
        
        # --- ПОЛЕ ВВОДА СООБЩЕНИЙ ---
        lbl_mailing = ctk.CTkLabel(settings_win, text="📨 New Message(s) to Add/Overwrite", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_mailing.pack(pady=10)

        tab_view = ctk.CTkTabview(settings_win, width=400, height=220)
        tab_view.pack(pady=5, padx=20)
        tab_widgets = []

        def create_tab_content(tab, msg_data):
            count_frame = ctk.CTkFrame(tab)
            count_frame.pack(fill="x", padx=5, pady=(5,0))
            ctk.CTkLabel(count_frame, text="Send this message N times:").pack(side="left", padx=5)
            count_entry = ctk.CTkEntry(count_frame, width=60)
            count_entry.insert(0, str(msg_data.get("count", 1)))
            count_entry.pack(side="left", padx=5)
            
            text_box = ctk.CTkTextbox(tab, width=380, height=160, font=ctk.CTkFont(size=12))
            text_box.insert("1.0", msg_data.get("text", ""))
            text_box.pack(fill="both", expand=True, padx=5, pady=5)
            return {"count_entry": count_entry, "text_box": text_box}

        for i, msg_data in enumerate(loaded_messages):
            tab_name = f"Message #{i+1}"
            tab = tab_view.add(tab_name)
            widgets = create_tab_content(tab, msg_data)
            tab_widgets.append(widgets)

        msg_controls_frame = ctk.CTkFrame(settings_win)
        msg_controls_frame.pack(pady=(5, 10))
        
        def add_message_tab():
            new_tab_name = f"Message #{len(tab_widgets) + 1}"
            tab = tab_view.add(new_tab_name)
            widgets = create_tab_content(tab, {"text": "", "count": 1})
            tab_widgets.append(widgets)
            tab_view.set(new_tab_name)

        def remove_message_tab():
            if len(tab_widgets) > 1:
                tab_name_to_remove = f"Message #{len(tab_widgets)}"
                tab_view.delete(tab_name_to_remove)
                tab_widgets.pop()

        btn_add_msg = ctk.CTkButton(msg_controls_frame, text="➕ Add Variation", command=add_message_tab)
        btn_add_msg.pack(side="left", padx=10)
        btn_remove_msg = ctk.CTkButton(msg_controls_frame, text="➖ Remove Last", command=remove_message_tab)
        btn_remove_msg.pack(side="left", padx=10)
        
        frm_gif = ctk.CTkFrame(settings_win)
        frm_gif.pack(pady=5, padx=20, fill="x")
        ctk.CTkLabel(frm_gif, text="Sent GIF's:", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
        media_var = tk.BooleanVar(value=loaded_cycle.media_enabled)
        media_switch = ctk.CTkSwitch(frm_gif, text="", variable=media_var)
        media_switch.pack(side="left", padx=5)

        # --- СБОР ДАННЫХ ---
        def get_messages_from_gui():
            new_msgs = []
            for widgets in tab_widgets:
                text = widgets["text_box"].get("1.0", "end-1c").strip()
                count_str = widgets["count_entry"].get().strip()
                if text:
                    try:
                        count = int(count_str) if count_str.isdigit() and int(count_str) > 0 else 1
                    except ValueError:
                        count = 1
                    new_msgs.append({"text": text, "count": count})
            return new_msgs

        def get_cycle_from_gui():
             return CycleSettings(
                messages_per_cycle=int(entry_messages.get()),
                rest_time_minutes=int(entry_rest.get()),
                retweet_count=int(entry_retweet_count.get()),
                max_total_retweets=int(entry_max_retweets.get()),
                media_enabled=bool(media_var.get())
            )

        # --- 🔴 ФУНКЦИЯ ПЕРЕЗАПИСИ (OVERWRITE) ---
        def save_overwrite_smart():
            update_settings = var_update_settings.get()
            update_messages = var_update_messages.get()

            if not update_settings and not update_messages:
                messagebox.showwarning("Warning", "Nothing selected to update!")
                return
            
            msgs_from_gui = []
            if update_messages:
                msgs_from_gui = get_messages_from_gui()
                if not msgs_from_gui:
                    if not messagebox.askyesno("Warning", "Message list is empty! This will DELETE all messages for selected accounts. Continue?"):
                        return

            if not messagebox.askyesno("Confirm", f"⚠️ OVERWRITE {len(selected_usernames)} accounts?\nOld messages will be DELETED."):
                return

            try:
                cycle_from_gui = get_cycle_from_gui() if update_settings else None

                for username in selected_usernames:
                    # Настройки
                    if update_settings:
                        final_cycle = cycle_from_gui
                    else:
                        final_cycle = self.cycle_manager.get_cycle_settings(username)

                    # Сообщения (ПОЛНАЯ ЗАМЕНА)
                    if update_messages:
                        final_msgs = msgs_from_gui 
                    else:
                        final_msgs = self.message_manager.get_messages(username)

                    self.save_settings_for_user(username, final_cycle, final_msgs)
                
                messagebox.showinfo("Success", "Overwrite completed!")
                settings_win.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        # --- 🟢 ФУНКЦИЯ ДОБАВЛЕНИЯ (APPEND) ---
        def save_append_smart():
            if not var_update_messages.get():
                messagebox.showwarning("Warning", "Enable 'Update Messages' checkbox to use Append!")
                return
            
            # Берем только то, что ввели сейчас в окне
            msgs_to_add = get_messages_from_gui()
            
            if not msgs_to_add:
                 messagebox.showwarning("Warning", "Please enter text to append.")
                 return

            if not messagebox.askyesno("Confirm", f"➕ APPEND new messages to {len(selected_usernames)} accounts?\nOld messages will be KEPT."):
                return
            
            try:
                cycle_from_gui = get_cycle_from_gui() if var_update_settings.get() else None

                for username in selected_usernames:
                    # Настройки
                    if var_update_settings.get():
                        final_cycle = cycle_from_gui
                    else:
                        # Если галочка снята, оставляем старые настройки каждого юзера
                        final_cycle = self.cycle_manager.get_cycle_settings(username)
                    
                    # Сообщения: Берем СТАРЫЕ (уникальные для юзера) + добавляем НОВЫЕ (общие)
                    # Добавляем проверку на уникальность
                    current_msgs = self.message_manager.get_messages(username)
                    for new_msg in msgs_to_add:
                        if new_msg not in current_msgs:
                            current_msgs.append(new_msg)
                    final_msgs = current_msgs
                    
                    self.save_settings_for_user(username, final_cycle, final_msgs)

                messagebox.showinfo("Success", f"Messages appended to {len(selected_usernames)} accounts!")
                settings_win.destroy()
            except Exception as e:
                messagebox.showerror("Error", str(e))


        btn_frame = ctk.CTkFrame(settings_win, fg_color="transparent")
        btn_frame.pack(pady=20)

        # КНОПКИ
        btn_apply = ctk.CTkButton(btn_frame, text="⚠️ Overwrite All", command=save_overwrite_smart, 
                                      font=ctk.CTkFont(size=14), fg_color="#c0392b", hover_color="#e74c3c", width=160)
        btn_apply.pack(side="left", padx=10)

        btn_append = ctk.CTkButton(btn_frame, text="➕ Append New", command=save_append_smart, 
                                   font=ctk.CTkFont(size=14), fg_color="green", hover_color="darkgreen", width=160)
        btn_append.pack(side="left", padx=10)

    def open_settings_window(self, account):
        settings_win = ctk.CTkToplevel(self.window)
        settings_win.title(f"Settings - {account['username']}")
        center_window(settings_win, 760, 660)
        settings_win.transient(self.window)
        settings_win.lift()
        settings_win.grab_set()

        if account["username"] not in self.account_manager.accounts:
            self.account_manager.accounts[account["username"]] = AccountState(account["username"])
            self.account_manager.accounts[account["username"]].groups = self.account_manager.load_saved_groups(account["username"])
        
        account_state = self.account_manager.accounts[account["username"]]
        saved_messages = self.message_manager.get_messages(account["username"])
        if not saved_messages:
            saved_messages = [{"text": "", "count": 1}]
        
        saved_cycle = self.cycle_manager.get_cycle_settings(account["username"])

        lbl_cycle = ctk.CTkLabel(settings_win, text=f"⚙️ {t('msg_cycle')}", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_cycle.pack(pady=10)
        frm_cycle = ctk.CTkFrame(settings_win)
        frm_cycle.pack(pady=5, padx=20, fill="x")
        ctk.CTkLabel(frm_cycle, text=f"{t('msg_cycle')}:").pack(side="left", padx=5)
        entry_messages = ctk.CTkEntry(frm_cycle, width=50)
        entry_messages.insert(0, str(saved_cycle.messages_per_cycle))
        entry_messages.pack(side="left", padx=5)
        ctk.CTkLabel(frm_cycle, text=f"{t('rt_count')}:").pack(side="left", padx=5)
        entry_retweet_count = ctk.CTkEntry(frm_cycle, width=50)
        entry_retweet_count.insert(0, str(saved_cycle.retweet_count))
        entry_retweet_count.pack(side="left", padx=5)
        ctk.CTkLabel(frm_cycle, text=f"{t('rest_time')}:").pack(side="left", padx=5)
        entry_rest = ctk.CTkEntry(frm_cycle, width=50)
        entry_rest.insert(0, str(saved_cycle.rest_time_minutes))
        entry_rest.pack(side="left", padx=5)
        
        # --- ИЗМЕНЕННАЯ НАДПИСЬ ---
        ctk.CTkLabel(frm_cycle, text="RT Limit (24h):").pack(side="left", padx=5)
        # --------------------------
        entry_max_retweets = ctk.CTkEntry(frm_cycle, width=50)
        entry_max_retweets.insert(0, str(saved_cycle.max_total_retweets))
        entry_max_retweets.pack(side="left", padx=5)
        
        lbl_mailing = ctk.CTkLabel(settings_win, text="📨 Mailing Messages", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_mailing.pack(pady=10)

        tab_view = ctk.CTkTabview(settings_win, width=400, height=220)
        tab_view.pack(pady=5, padx=20)
        tab_widgets = []

        def create_tab_content(tab, msg_data):
            count_frame = ctk.CTkFrame(tab)
            count_frame.pack(fill="x", padx=5, pady=(5,0))
            
            ctk.CTkLabel(count_frame, text="Send this message N times:").pack(side="left", padx=5)
            count_entry = ctk.CTkEntry(count_frame, width=60)
            count_entry.insert(0, str(msg_data.get("count", 1)))
            count_entry.pack(side="left", padx=5)
            
            text_box = ctk.CTkTextbox(tab, width=380, height=160, font=ctk.CTkFont(size=12))
            text_box.insert("1.0", msg_data.get("text", ""))
            text_box.pack(fill="both", expand=True, padx=5, pady=5)
            
            return {"count_entry": count_entry, "text_box": text_box}

        for i, msg_data in enumerate(saved_messages):
            tab_name = f"Message #{i+1}"
            tab = tab_view.add(tab_name)
            widgets = create_tab_content(tab, msg_data)
            tab_widgets.append(widgets)

        msg_controls_frame = ctk.CTkFrame(settings_win)
        msg_controls_frame.pack(pady=(5, 10))
        
        def add_message_tab():
            new_tab_name = f"Message #{len(tab_widgets) + 1}"
            tab = tab_view.add(new_tab_name)
            widgets = create_tab_content(tab, {"text": "", "count": 1})
            tab_widgets.append(widgets)
            tab_view.set(new_tab_name)

        def remove_message_tab():
            if len(tab_widgets) > 1:
                tab_name_to_remove = f"Message #{len(tab_widgets)}"
                tab_view.delete(tab_name_to_remove)
                tab_widgets.pop()

        btn_add_msg = ctk.CTkButton(msg_controls_frame, text="➕ Add Variation", command=add_message_tab)
        btn_add_msg.pack(side="left", padx=10)
        btn_remove_msg = ctk.CTkButton(msg_controls_frame, text="➖ Remove Last", command=remove_message_tab)
        btn_remove_msg.pack(side="left", padx=10)
        
        frm_gif = ctk.CTkFrame(settings_win)
        frm_gif.pack(pady=5, padx=20, fill="x")
        ctk.CTkLabel(frm_gif, text="Sent GIF's:", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
        media_var = tk.BooleanVar(value=saved_cycle.media_enabled)
        media_switch = ctk.CTkSwitch(frm_gif, text="", variable=media_var)
        media_switch.pack(side="left", padx=5)

        groups_frame = ctk.CTkFrame(settings_win)
        groups_frame.pack(pady=10, padx=20, fill="x")
        lbl_groups = ctk.CTkLabel(groups_frame, text=f"👥 {t('groups')}", font=ctk.CTkFont(size=16, weight="bold"))
        lbl_groups.pack(pady=5)
        groups_count = len(account_state.groups)
        lbl_groups_count = ctk.CTkLabel(groups_frame, text=f"Current Groups: {groups_count}", font=ctk.CTkFont(size=12))
        lbl_groups_count.pack(pady=5)
        groups_buttons_frame = ctk.CTkFrame(groups_frame)
        groups_buttons_frame.pack(pady=5, fill="x")
        btn_parse = ctk.CTkButton(groups_buttons_frame, text="🔍 Parse Groups", command=lambda: self.non_blocking_parse(account["username"]))
        btn_parse.pack(side="left", padx=5, expand=True)
        btn_clear = ctk.CTkButton(groups_buttons_frame, text="🗑 Clear Groups", command=lambda: self.clear_groups_for(account["username"]))
        btn_clear.pack(side="left", padx=5, expand=True)

        def save_and_close():
            all_messages_data = []
            for widgets in tab_widgets:
                text = widgets["text_box"].get("1.0", "end-1c").strip()
                count_str = widgets["count_entry"].get().strip()
                
                if text:
                    try:
                        count = int(count_str) if count_str.isdigit() and int(count_str) > 0 else 1
                    except ValueError:
                        count = 1
                    all_messages_data.append({"text": text, "count": count})
            
            try:
                new_cycle = CycleSettings(
                    messages_per_cycle=int(entry_messages.get()),
                    rest_time_minutes=int(entry_rest.get()),
                    retweet_count=int(entry_retweet_count.get()),
                    max_total_retweets=int(entry_max_retweets.get()),
                    media_enabled=bool(media_var.get())
                )
                self.save_settings_for_user(account["username"], new_cycle, all_messages_data)
                # Messagebox removed
                settings_win.destroy()

            except ValueError:
                messagebox.showerror("Error", "Invalid settings values!")


        btn_save = ctk.CTkButton(settings_win, text=t("save_settings"), command=save_and_close, font=ctk.CTkFont(size=14))
        btn_save.pack(pady=10)

    def save_settings_for_user(self, username: str, cycle_settings: CycleSettings, messages_list: List[Dict[str, Any]]):
        """Сохраняет настройки цикла и сообщений для указанного пользователя."""
        self.cycle_manager.save_cycle_settings(username, cycle_settings)
        self.message_manager.save_messages(username, messages_list)

        account_state = self.account_manager.accounts.get(username)
        if account_state:
            account_state.cycle_settings = cycle_settings
            account_state.mailing_messages = messages_list
            account_state.media_enabled = cycle_settings.media_enabled
            # Сбрасываем прогресс рассылки, так как сообщения изменились
            account_state.message_index = 0
            account_state.message_sent_count = 0
        
        self.logger.info(f"Settings updated for {username}: Cycle={cycle_settings}, Messages Count={len(messages_list)}", username)
        self.update_account_table()


    async def main_loop(self):
        if not hasattr(self, 'app_is_authorized') or not self.app_is_authorized:
            return
            
        while True:
            try:
                self.window.update()
                await asyncio.sleep(0.02)
            except tk.TclError:
                break

async def main():
    gui = GUI()
    try:
        if hasattr(gui, 'app_is_authorized') and gui.app_is_authorized:
            await gui.main_loop()
    except Exception as e:
        print(f"Application error: {str(e)}")
    finally:
        print("Application closing...")
        if hasattr(gui, 'account_manager'):
            gui.account_manager.shutdown_all_browsers()
        print("Application closed")

if __name__ == "__main__":
    # Предварительная очистка, если остались висеть процессы с прошлого раза
    force_kill_chromedrivers()

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Application terminated by user")
    finally:
        # Финальная очистка при любом выходе из программы
        print("Final cleanup...")
        force_kill_chromedrivers()
        sys.exit(0)