"""
Уникализация текста, экранирование для Telegram, разбор чисел.
"""

import html
import random
import re


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
