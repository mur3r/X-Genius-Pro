"""
Запуск приложения: локальный веб-сервер (aiohttp) + движок рассылки в одном asyncio-цикле.
Интерфейс открывается в браузере на http://127.0.0.1:8765 (см. xgenius/web/).
"""
from xgenius.web.server import serve


def run() -> None:
    serve()
