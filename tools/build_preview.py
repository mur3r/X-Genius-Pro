"""
Собирает xgenius/web/static/preview.html — одностраничную копию интерфейса со встроенными
CSS/JS. Её можно открыть двойным кликом без запущенного сервиса: покажет демо-данные.
Запуск: python tools/build_preview.py
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "xgenius" / "web" / "static"


def build() -> Path:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")

    def inline_script(m):
        name = m.group(1)
        js = (STATIC / name).read_text(encoding="utf-8")
        return f"<script>\n/* ---- {name} ---- */\n{js}\n</script>"

    html = re.sub(r'<script src="([a-z]+\.js)"></script>', inline_script, html)
    html = html.replace("<title>X-Genius</title>", "<title>X-Genius (preview)</title>")
    out = STATIC / "preview.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    print("written:", build())
