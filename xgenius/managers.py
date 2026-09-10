"""
Настройки на аккаунт: сообщения рассылки, параметры цикла, комментарии (JSON).
"""

import json
from typing import Any, Dict, List

from xgenius.config import Config
from xgenius.logger import Logger
from xgenius.models import CommentSettings, CycleSettings


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
