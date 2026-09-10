"""
X-Genius — бот массовой рассылки в групповые чаты X (Twitter) через Selenium.

Точка входа: main.py -> xgenius.app.run(). Структура пакета описана в README.md.
"""
import logging
import warnings

import urllib3

__version__ = "2026.09"

# Подавляем предупреждения о устаревшем get_event_loop и шум urllib3/requests
warnings.filterwarnings("ignore", category=DeprecationWarning, module="asyncio")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.HTTPWarning)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
