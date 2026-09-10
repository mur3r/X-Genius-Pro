"""
Точка входа X-Genius. Запуск из папки проекта:

    python main.py

Весь код живёт в пакете xgenius/ (см. README.md). Этот файл оставлен, чтобы
существующие ярлыки / сборки, запускающие main.py, продолжали работать.
"""
from xgenius.app import run

if __name__ == "__main__":
    run()
