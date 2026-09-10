"""
SQLite-хранилище мониторинга (используется Telegram-ботом).
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional


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
