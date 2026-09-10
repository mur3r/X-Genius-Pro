"""
Веб-интерфейс X-Genius (замена tkinter):
  engine.py  — сборка движка (менеджеры, планировщик), снимок состояния для UI, логи;
  actions.py — операции над аккаунтами (логин, парсинг, рассылка, настройки, статистика);
  server.py  — aiohttp: JSON API, WebSocket с живым состоянием/логами, статика, запуск.
Страница: static/index.html (+ app.js, dialogs.js, style.css, help.txt).
"""
