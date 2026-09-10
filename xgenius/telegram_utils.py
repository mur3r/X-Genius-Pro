"""
Безопасная отправка/редактирование сообщений Telegram (HTML с fallback).
"""


async def safe_send_message(bot, chat_id: str, text: str, **kwargs) -> bool:
    """
    Безопасно отправляет сообщение с HTML форматированием.
    Все динамические данные должны быть предварительно экранированы через escape_html().
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", **kwargs)
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Если ошибка связана с парсингом HTML, пробуем без форматирования
        if "can't parse entities" in error_str or "parse" in error_str:
            try:
                # Пробуем отправить как plain text (без parse_mode)
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=None, **kwargs)
                return True
            except Exception as e2:
                print(f"Error sending message without formatting: {e2}")
                return False
        else:
            print(f"Error sending message: {e}")
            return False


async def safe_reply_text(message, text: str, **kwargs) -> bool:
    """
    Безопасно отвечает на сообщение с HTML форматированием.
    Все динамические данные должны быть предварительно экранированы через escape_html().
    """
    try:
        await message.reply_text(text=text, parse_mode="HTML", **kwargs)
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Если ошибка связана с парсингом HTML, пробуем без форматирования
        if "can't parse entities" in error_str or "parse" in error_str:
            try:
                await message.reply_text(text=text, parse_mode=None, **kwargs)
                return True
            except Exception as e2:
                print(f"Error replying without formatting: {e2}")
                return False
        else:
            print(f"Error replying: {e}")
            return False


async def safe_edit_message_text(query, text: str, **kwargs) -> bool:
    """
    Безопасно редактирует сообщение с HTML форматированием.
    Все динамические данные должны быть предварительно экранированы через escape_html().
    Также обрабатывает ошибку "Message is not modified".
    """
    try:
        await query.edit_message_text(text=text, parse_mode="HTML", **kwargs)
        return True
    except Exception as e:
        error_str = str(e).lower()
        # Если ошибка связана с парсингом HTML, пробуем без форматирования
        if "can't parse entities" in error_str or "parse" in error_str:
            try:
                await query.edit_message_text(text=text, parse_mode=None, **kwargs)
                return True
            except Exception as e2:
                # Проверяем, не изменилось ли сообщение
                if "message is not modified" in str(e2).lower():
                    return True  # Считаем это успехом
                print(f"Error editing message without formatting: {e2}")
                return False
        # Если сообщение не было изменено, считаем это успехом
        elif "message is not modified" in error_str:
            return True
        else:
            print(f"Error editing message: {e}")
            return False
