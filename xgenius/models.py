"""
Модели данных: настройки цикла/комментариев, учётные данные, состояние аккаунта.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from selenium import webdriver

from human1 import Humanizer

from xgenius.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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
