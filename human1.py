import time
import tkinter as tk
import pyperclip
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import random
import queue
import threading


class Humanizer:
    def __init__(self):
        self.enabled = False
        self.typing_speed = {
            'slow': (0.1, 0.3),
            'normal': (0.05, 0.15),
            'fast': (0.02, 0.08)
        }
        self.pause_between_actions = (1, 4)
        self.typo_chance = 0.02
        self.correction_delay = (0.5, 1.5)
        self.word_pause_chance = 0.15
        self.word_pause_range = (0.5, 1.5)
        self.thinking_phrases = [
            "Thinking about message...",
            "Choosing words...",
            "Contemplating...",
            "Composing response..."
        ]
        self.gif_selection_phrases = [
            "Browsing GIF gallery",
            "Looking for the perfect GIF",
            "Searching through categories",
            "Finding something interesting"
        ]
        self.rewrite_chance = 0.05
        self.browser = None
        self.gui_queue = queue.Queue()
        self.is_typing = False
        self.active_threads = set()
        self._shutdown = threading.Event()

    def set_browser(self, browser):
        self.browser = browser

    def get_typing_speed(self):
        current_hour = datetime.now().hour
        if 0 <= current_hour < 6:
            return self.typing_speed['slow']
        elif 10 <= current_hour < 20:
            return self.typing_speed['fast']
        else:
            return self.typing_speed['normal']

    def safe_update_log(self, log_widget, text):
        """Безопасное обновление лога через очередь"""
        if hasattr(log_widget, 'after'):
            log_widget.after(0, lambda: self._update_log(log_widget, text))

    def _update_log(self, log_widget, text):
        """Непосредственное обновление виджета лога"""
        try:
            if hasattr(log_widget, 'winfo_exists') and log_widget.winfo_exists():
                log_widget.insert(tk.END, text)
                log_widget.see(tk.END)
        except Exception as e:
            print(f"Log update error: {e}")

    def get_textbox_element(self):
        """Получаем актуальный элемент текстового поля"""
        if self.browser:
            try:
                return WebDriverWait(self.browser, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@role='textbox']"))
                )
            except Exception:
                return None
        return None

    def shutdown(self):
        """Останавливает все операции гуманизации"""
        self._shutdown.set()
        self.is_typing = False
        for thread in list(self.active_threads):
            if thread.is_alive():
                thread.join(timeout=1.0)
        self.active_threads.clear()
        self._shutdown.clear()

    def _add_thread(self, thread):
        """Добавляет поток в список активных"""
        self.active_threads.add(thread)
        thread.daemon = True
        return thread

    def _remove_thread(self, thread):
        """Удаляет поток из списка активных"""
        self.active_threads.discard(thread)

    def simulate_typing(self, element, text, log_text_widget):
        if not self.enabled:
            if element:
                pyperclip.copy(text)
                element.send_keys(Keys.CONTROL, 'v')
                time.sleep(1)
                element.send_keys(Keys.RETURN)
                return True

        def type_text():
            try:
                typing_completed = False
                textbox = element if element else self.get_textbox_element()
                if not textbox:
                    self.safe_update_log(log_text_widget, "❌ Cannot find text input field\n")
                    return False

                self.safe_update_log(log_text_widget, "⌨️ Typing message...\n")
                textbox.click()

                for line in text.split("\n"):
                    if self._shutdown.is_set() or not self.is_typing:
                        break

                    for word in line.split():
                        if self._shutdown.is_set() or not self.is_typing:
                            break

                        for char in word:
                            if self._shutdown.is_set() or not self.is_typing:
                                break

                            if random.random() < self.typo_chance:
                                typo_char = self._get_typo_char(char)
                                textbox.send_keys(typo_char)
                                self.safe_update_log(log_text_widget, "🔄 Fixing typo...\n")
                                self._shutdown.wait(timeout=random.uniform(*self.correction_delay))
                                textbox.send_keys(Keys.BACKSPACE)

                            textbox.send_keys(char)

                            delay = random.uniform(*self.get_typing_speed())
                            if char in '.!?,:;':
                                delay += random.uniform(0.3, 0.7)
                            self._shutdown.wait(timeout=delay)

                        textbox.send_keys(' ')

                        if random.random() < self.word_pause_chance:
                            self._shutdown.wait(timeout=random.uniform(*self.word_pause_range))

                    textbox.send_keys(Keys.SHIFT, Keys.ENTER)
                    self._shutdown.wait(timeout=random.uniform(0.3, 0.7))

                self.safe_update_log(log_text_widget, "✉️ Finishing message...\n")
                textbox.send_keys(Keys.RETURN)
                typing_completed = True
                return typing_completed

            except Exception as e:
                self.safe_update_log(log_text_widget, f"❌ Typing error: {e}\n")
                return False
            finally:
                self.is_typing = False
                self._remove_thread(threading.current_thread())

        self.is_typing = True
        thread = threading.Thread(target=type_text, daemon=True)
        self._add_thread(thread)
        thread.start()

        thread.join()
        return True

    def _get_typo_char(self, char):
        """Получение символа для опечатки"""
        keyboard_layout = {
            'q': 'wsa', 'w': 'qesd', 'e': 'wrdf', 'r': 'etfg',
            't': 'rygh', 'y': 'tuhj', 'u': 'yijk', 'i': 'uokl',
            'o': 'iplk', 'p': 'ol', 'a': 'qwsz', 's': 'awedxz',
            'd': 'serfcx', 'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb',
            'j': 'huikmn', 'k': 'jiolm', 'l': 'kop', 'z': 'asx',
            'x': 'zsdc', 'c': 'xdfv', 'v': 'cfgb', 'b': 'vghn',
            'n': 'bhjm', 'm': 'njk'
        }

        if char.lower() in keyboard_layout:
            typo_char = random.choice(keyboard_layout[char.lower()])
            return typo_char.upper() if char.isupper() else typo_char
        return char

    def simulate_thinking(self, log_text_widget):
        """Симуляция размышления перед печатью"""
        if not self.enabled:
            return

        thinking_time = random.uniform(2, 7)
        self.safe_update_log(log_text_widget, "💭 Thinking about message...\n")
        self._shutdown.wait(timeout=thinking_time)

    def random_pause(self, action_name, log_text_widget):
        """Случайная пауза между действиями"""
        if not self.enabled:
            return 0

        pause_time = random.uniform(*self.pause_between_actions)
        self.safe_update_log(log_text_widget, f"💭 {action_name}... ({pause_time:.1f}s)\n")
        self._shutdown.wait(timeout=pause_time)
        return pause_time

    def simulate_gif_selection(self, log_text_widget):
        """Симуляция выбора GIF"""
        if not self.enabled:
            return

        actions = [
            "Browsing GIF gallery",
            "Selecting perfect GIF",
            "Looking for something interesting",
            "Scrolling through categories"
        ]

        for _ in range(random.randint(2, 4)):
            action = random.choice(actions)
            self.random_pause(action, log_text_widget)
        return True