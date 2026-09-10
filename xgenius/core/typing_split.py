"""
Разбиение текста на порции для "человеческого" набора.

ChromeDriver умеет send_keys только для символов из BMP (U+0000..U+FFFF); любой
emoji вне BMP (🔥 💖 🚀 ...) роняет send_keys исключением
"ChromeDriver only supports characters in the BMP". Такие символы (и склеенные
с ними ZWJ/VS16-последовательности) отдаём как 'insert' — их вставляют через
CDP Input.insertText, что для React выглядит как обычный ввод.
Символы вроде ☭ 卐 ♫ ✰ находятся в BMP и печатаются как обычные клавиши.
"""
import unicodedata
from typing import List, Tuple


def is_bmp(ch: str) -> bool:
    return ord(ch) <= 0xFFFF


def _joins_previous(ch: str) -> bool:
    """Символы, которые склеиваются с предыдущим: ZWJ, variation selectors, комбинирующие."""
    if ch in ("‍", "️", "︎"):
        return True
    return unicodedata.category(ch).startswith("M")


def split_for_typing(text: str) -> List[Tuple[str, str]]:
    """Делит текст на порции: ('newline', '\\n') | ('key', <1 BMP-символ>) | ('insert', <строка>)."""
    out: List[Tuple[str, str]] = []
    run = ""
    for ch in text:
        if ch == "\n":
            if run:
                out.append(("insert", run))
                run = ""
            out.append(("newline", "\n"))
            continue
        if ch == "\r":
            continue
        if not is_bmp(ch) or (run and _joins_previous(ch)):
            run += ch
            continue
        if _joins_previous(ch) and out and out[-1][0] == "key":
            # VS16 после BMP-символа (❤ + FE0F): склеиваем в insert, чтобы не разорвать пару
            prev = out.pop()[1]
            run = prev + ch
            continue
        if run:
            out.append(("insert", run))
            run = ""
        out.append(("key", ch))
    if run:
        out.append(("insert", run))
    return out
