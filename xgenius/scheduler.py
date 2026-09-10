"""
TaskScheduler: цикл рассылки, очередь групп, восстановление браузера.
"""

import asyncio
import os
import random
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from xgenius.accounts.manager import AccountManager
from xgenius.core import (
    BROWSER_CLOSED,
    ChatStore,
    DISABLED_TTL_HOURS,
    FAILED,
    LIMIT_REACHED,
    LOCKED,
    NEED_RELOGIN,
    NO_INPUT,
    NO_INPUT_STRIKES_TO_DISABLE,
    RETRY,
    SUCCESS,
)
from xgenius.logger import Logger
from xgenius.models import AccountState
from xgenius.settings import (
    DM_LIMIT_PAUSE_SECONDS,
    HEALTH_TIMEOUT_STRIKES,
    RECOVERY_MAX_ATTEMPTS,
    SEND_STALL_PAUSE_SECONDS,
    SEND_STALL_THRESHOLD,
)
from xgenius.text_utils import generate_unique_message_from_raw
from xgenius.twitter.operations import TwitterOperations


class TaskScheduler:
    def __init__(self, logger: Logger, gui_update_callback: Callable, account_manager: AccountManager):
        self.logger = logger
        self.running_tasks = {}
        self.tasks_lock = threading.Lock()  # Lock for thread-safe access to running_tasks
        self.gui_update_callback = gui_update_callback
        self.account_manager = account_manager
        self.telegram_bot_manager = None
        # Группы: кеш / очередь / страйки / отключённые (см. ChatStore).
        # chat_cache.json и chat_queue.json остаются там же, где были (текущая папка),
        # плюс chat_state.json со страйками.
        self.chat_store = ChatStore(Path.cwd(), logger=self.logger)

    def set_telegram_bot(self, bot_manager):
        """Раньше вызывался из GUI, но не существовал."""
        self.telegram_bot_manager = bot_manager

    async def _refresh_ichat_groups(self, account_state, twitter_ops):
        """
        Перед рассылкой собираем группы из iChat и ОБЪЕДИНЯЕМ с кешем.

        Раньше кеш ЗАМЕНЯЛСЯ результатом парсинга: если X подгрузил список не до конца
        (ленивая подгрузка, "something went wrong", медленный прокси), часть групп
        "исчезала из базы" — это и есть та самая "программа удаляет группу". Кроме того,
        при неудачной отправке группа снималась с очереди и не возвращалась до полного
        обхода. Теперь группы только добавляются; недоступные помечаются отключёнными
        по страйкам (ChatStore.report) и через DISABLED_TTL_HOURS пробуются снова.
        """
        username = account_state.username
        self.logger.info("Начинаем сбор групп из iChat...", username)

        found = await twitter_ops.find_groups(account_state.browser, username)
        all_groups, added = self.chat_store.merge_parsed(username, found)

        if not found:
            self.logger.warning(f"iChat не вернул ссылок. Используем кеш: {len(all_groups)} групп.", username)
        else:
            self.logger.info(
                f"📦 Парсинг: найдено {len(found)}, новых {added}, всего в кеше {len(all_groups)}, "
                f"отключено {len(self.chat_store.disabled_groups(username))}", username)

        if all_groups:
            account_state.groups = set(all_groups)
            self.account_manager.save_groups()
        return all_groups

    async def _recover_browser(self, account_state: AccountState, account_manager: AccountManager, why: str) -> Optional[AccountState]:
        """
        Восстановление после BROWSER_CLOSED / NEED_RELOGIN: закрыть мёртвый браузер,
        открыть новый, войти (профиль/куки/токены/пароль) и вернуть свежий state.
        Попытки с backoff 60s, 120s, 240s ... (макс 10 мин), RECOVERY_MAX_ATTEMPTS раз.
        Раньше при BROWSER_CLOSED цикл просто завершался и аккаунт оставался inactive.
        """
        username = account_state.username
        for attempt in range(1, RECOVERY_MAX_ATTEMPTS + 1):
            if not account_state.is_active:
                return None
            account_state.status_reason = "RECOVERING"
            self.gui_update_callback()
            self.logger.warning(f"Восстановление браузера ({why}), попытка {attempt}/{RECOVERY_MAX_ATTEMPTS}...", username)
            ok = await account_manager.auto_relogin_if_needed(username, force=True)
            new_state = account_manager.accounts.get(username)
            if ok and new_state and new_state.browser:
                new_state.is_active = True
                new_state.is_mailing = True
                new_state.status_reason = ""
                new_state.need_relogin = False
                self.gui_update_callback()
                self.logger.info("Браузер восстановлен, продолжаем рассылку с той же очереди.", username)
                return new_state
            delay = min(600, 60 * (2 ** (attempt - 1)))
            self.logger.warning(f"Восстановление не удалось. Следующая попытка через {delay}s.", username)
            await asyncio.sleep(delay)
        return None

    async def start_sending_cycle(self, account_state: AccountState, twitter_ops: TwitterOperations, account_manager: AccountManager, humanize: bool = True):
            username = account_state.username
            try:
                if self.telegram_bot_manager:
                    self.telegram_bot_manager.refresh_temp_messages_from_db()

                # Humanizer из human1.py: параметры набора берём отсюда (см. _type_message_sync)
                account_state.humanizer.enabled = humanize
                try:
                    account_state.humanizer.set_browser(account_state.browser)
                except Exception:
                    pass

                fresh_groups = await self._refresh_ichat_groups(account_state, twitter_ops)
                if not fresh_groups:
                    self.logger.error("Нет доступных iChat-групп (ни в iChat, ни в кеше). Останавливаем цикл.", username)
                    return

                messages_to_send = list(account_state.mailing_messages)
                if not messages_to_send:
                    self.logger.error("Список сообщений для рассылки пуст. Останавливаем цикл.", username)
                    return

                cycle_messages_limit = account_state.cycle_settings.messages_per_cycle
                rest_time_seconds = account_state.cycle_settings.rest_time_minutes * 60

                self.logger.info(f"Начинаем цикл отправки для {username}.", username)

                health_timeouts = 0
                unconfirmed_streak = 0   # подряд RETRY/unconfirmed — признак скрытого лимита
                idle_streak = 0          # подряд попыток без SUCCESS по любой причине

                while account_state.is_active:
                    spec_count = 0
                    spec_msgs = []
                    if self.telegram_bot_manager:
                        self.telegram_bot_manager.refresh_temp_messages_from_db()
                        tm = self.telegram_bot_manager.temp_messages
                        tm["sent_this_cycle"] = False
                        spec_msgs = tm.get("messages", [])
                        spec_count = len(spec_msgs)

                    account_state.spec_sent_count = 0
                    account_state.spec_total_remaining = spec_count
                    account_state.spec_random_pos = random.randint(3, max(3, int(cycle_messages_limit * 0.8)))

                    messages_sent_this_cycle = 0

                    while messages_sent_this_cycle < cycle_messages_limit:
                        if not account_state.is_active:
                            break

                        # --- Здоровье браузера: таймаут != закрыт ---
                        health = await account_manager.check_browser_health_detailed(account_state.browser)
                        if health == "TIMEOUT":
                            health_timeouts += 1
                            if health_timeouts < HEALTH_TIMEOUT_STRIKES:
                                self.logger.warning(
                                    f"Браузер отвечает медленно ({health_timeouts}/{HEALTH_TIMEOUT_STRIKES}). Ждём 20с.", username)
                                await asyncio.sleep(20)
                                continue
                            health = "CLOSED"
                        else:
                            health_timeouts = 0

                        if health == "CLOSED":
                            self.logger.warning("Браузер закрыт/не отвечает. Пробуем восстановить.", username)
                            new_state = await self._recover_browser(account_state, account_manager, "browser closed")
                            if not new_state:
                                account_state.is_active = False
                                account_state.browser = None
                                account_state.status_reason = "BROWSER_CLOSED"
                                self.gui_update_callback()
                                break
                            account_state = new_state
                            health_timeouts = 0
                            continue

                        while account_state.is_paused:
                            await asyncio.sleep(2)

                        # --- Перелогин ---
                        if account_state.need_relogin:
                            self.logger.info("Аккаунту нужен перелогин.", username)
                            new_state = await self._recover_browser(account_state, account_manager, "relogin")
                            if not new_state:
                                account_state.is_active = False
                                account_state.status_reason = "RELOGIN FAILED"
                                self.gui_update_callback()
                                break
                            account_state = new_state
                            continue

                        if account_state.message_index >= len(messages_to_send):
                            account_state.message_index = 0
                            account_state.message_sent_count = 0

                        current_message_obj = messages_to_send[account_state.message_index]
                        current_message_text = current_message_obj.get("text", "")
                        required_send_count = int(current_message_obj.get("count", 1))

                        if not current_message_text:
                            account_state.message_index = (account_state.message_index + 1) % len(messages_to_send)
                            account_state.message_sent_count = 0
                            continue

                        current_group = self.chat_store.next_chat(username)
                        if not current_group:
                            self.logger.error("Все группы отключены или очередь пуста. Останавливаем цикл.", username)
                            break

                        wait_time = random.uniform(15, 30)
                        self.logger.info(
                            f"Отправляем в {current_group} (ждем {wait_time:.1f}с; в очереди {self.chat_store.queue_len(username)})...",
                            username)
                        await asyncio.sleep(wait_time)

                        status = await twitter_ops.send_message(
                            state=account_state,
                            group_url=current_group,
                            message_text=current_message_text,
                            humanize=humanize
                        )

                        if status == BROWSER_CLOSED:
                            self.chat_store.requeue(username, current_group)
                            self.logger.warning("Браузер закрылся во время отправки. Пробуем восстановить.", username)
                            new_state = await self._recover_browser(account_state, account_manager, "browser closed")
                            if not new_state:
                                account_state.is_active = False
                                account_state.browser = None
                                account_state.status_reason = "BROWSER_CLOSED"
                                self.gui_update_callback()
                                break
                            account_state = new_state
                            continue

                        elif status == NEED_RELOGIN:
                            self.chat_store.requeue(username, current_group)
                            self.logger.warning("Аккаунту нужен перелогин. Устанавливаем флаг...", username)
                            account_state.need_relogin = True
                            account_state.status_reason = "RELOGIN"
                            self.gui_update_callback()
                            continue

                        elif status == LOCKED:
                            self.chat_store.requeue(username, current_group)
                            await account_manager.handle_lock_if_any(username)
                            self.gui_update_callback()
                            break

                        elif status == NO_INPUT:
                            idle_streak += 1
                            event = self.chat_store.report(username, current_group, NO_INPUT, "no composer")
                            st = self.chat_store.group_state(username, current_group)
                            if event == "disabled":
                                self.logger.error(
                                    f"⛔ Группа {current_group} отключена на {DISABLED_TTL_HOURS}ч: "
                                    f"{st.get('reason')}. Из кеша НЕ удалена.", username)
                            else:
                                self.logger.warning(
                                    f"❌ Нет поля ввода в {current_group} "
                                    f"(страйк {st.get('no_input', 0)}/{NO_INPUT_STRIKES_TO_DISABLE}). "
                                    f"Группа возвращена в конец очереди.", username)
                            await asyncio.sleep(random.uniform(4, 8))

                        elif status in (RETRY, FAILED):
                            idle_streak += 1
                            unconfirmed_streak += 1
                            event = self.chat_store.report(username, current_group, RETRY, "temporary error")
                            st = self.chat_store.group_state(username, current_group)
                            if event == "disabled":
                                self.logger.error(
                                    f"⛔ Группа {current_group} даёт ошибки {st.get('retry')} раз подряд — "
                                    f"отключена на {DISABLED_TTL_HOURS}ч (из кеша НЕ удалена).", username)
                            else:
                                self.logger.warning(
                                    f"⚠️ Временная ошибка в {current_group} (retry {st.get('retry', 0)}). "
                                    f"Группу НЕ удаляем — вернули в конец очереди.", username)
                            if unconfirmed_streak >= SEND_STALL_THRESHOLD:
                                self.logger.warning(
                                    f"🛑 {unconfirmed_streak} отправок подряд не прошли. Похоже на скрытый лимит DM "
                                    f"или сбой X. Пауза {SEND_STALL_PAUSE_SECONDS // 60} мин + проверка сессии.", username)
                                account_state.status_reason = f"SEND STALL {SEND_STALL_PAUSE_SECONDS // 60}M"
                                self.gui_update_callback()
                                await asyncio.sleep(SEND_STALL_PAUSE_SECONDS)
                                account_state.status_reason = ""
                                unconfirmed_streak = 0
                                await account_manager.handle_lock_if_any(username)
                                self.gui_update_callback()
                            else:
                                await asyncio.sleep(random.uniform(4, 8))

                        elif status == LIMIT_REACHED:
                            self.chat_store.requeue(username, current_group)
                            self.logger.warning(f"🛑 ДОСТИГНУТ ЛИМИТ DM! Пауза {DM_LIMIT_PAUSE_SECONDS // 3600} ч...", username)
                            account_state.status_reason = f"DM LIMIT {DM_LIMIT_PAUSE_SECONDS // 3600}H"
                            self.gui_update_callback()
                            await asyncio.sleep(DM_LIMIT_PAUSE_SECONDS)
                            account_state.status_reason = ""
                            unconfirmed_streak = 0
                            self.gui_update_callback()

                        elif status == SUCCESS:
                            idle_streak = 0
                            unconfirmed_streak = 0
                            self.chat_store.report(username, current_group, SUCCESS)
                            account_state.messages_sent += 1
                            account_state.message_sent_count += 1
                            account_state.last_action_time = datetime.now()
                            messages_sent_this_cycle += 1
                            # Раньше статистика сообщений (History / Stat) вообще не записывалась
                            try:
                                twitter_ops.stats_manager.record_message_sent(username)
                            except Exception as e:
                                self.logger.warning(f"Не удалось записать статистику: {e}", username)

                            # --- Логика отправки спец-сообщений ---
                            should_send_spec = False
                            if spec_count == 1 and account_state.spec_sent_count == 0 and account_state.spec_total_remaining > 0:
                                if messages_sent_this_cycle >= account_state.spec_random_pos:
                                    should_send_spec = True
                            elif spec_count >= 2 and account_state.spec_total_remaining > 0:
                                if messages_sent_this_cycle % 5 == 0 and account_state.spec_sent_count < spec_count:
                                    should_send_spec = True

                            if spec_msgs and should_send_spec:
                                idx_to_send = account_state.spec_sent_count % spec_count
                                temp_msg = spec_msgs[idx_to_send]
                                enabled_now = self.chat_store.enabled_groups(username) or fresh_groups
                                special_group = random.choice(enabled_now)

                                wait_time_temp = random.uniform(15, 30)
                                self.logger.info(f"Отправляем СПЕЦ СООБЩЕНИЕ в {special_group} (ждем {wait_time_temp:.1f}с)...", username)
                                await asyncio.sleep(wait_time_temp)

                                status_temp = await twitter_ops.send_message(
                                    state=account_state,
                                    group_url=special_group,
                                    message_text=temp_msg,
                                    humanize=True
                                )

                                if status_temp == SUCCESS:
                                    pc_id = getattr(self.telegram_bot_manager.config, 'pc_id', 'PC_UNKNOWN') if self.telegram_bot_manager else "PC_UNKNOWN"
                                    notification = f"[{pc_id}] Аккаунт @{username} отправил спец сообщение в {special_group}"
                                    try:
                                        if self.telegram_bot_manager:
                                            await self.telegram_bot_manager.bot.send_message(
                                                chat_id=self.telegram_bot_manager.config.chat_id,
                                                text=notification
                                            )
                                    except Exception as e:
                                        self.logger.error(f"Failed to send notification: {e}", username)
                                else:
                                    self.logger.warning(f"Failed to send special message: {status_temp}", username)

                                account_state.spec_sent_count += 1
                                account_state.spec_total_remaining -= 1

                        if idle_streak >= 30:
                            self.logger.warning(
                                "30 попыток подряд без успешной отправки. Мягкое восстановление (/home) и пауза 5 мин.", username)
                            idle_streak = 0
                            await account_manager.handle_lock_if_any(username)
                            self.gui_update_callback()
                            await asyncio.sleep(300)

                        if account_state.message_sent_count >= required_send_count:
                            account_state.message_index = (account_state.message_index + 1) % len(messages_to_send)
                            account_state.message_sent_count = 0

                    if not account_state.is_active:
                        break

                    self.logger.info(f"Цикл завершен. Готовимся к отдыху ({account_state.cycle_settings.rest_time_minutes}м)...", username)

                    # --- Комментирование в перерыве ---
                    comm_sets = account_state.comment_settings
                    if datetime.now() - account_state.last_comment_time > timedelta(days=1):
                        account_state.comments_sent_24h = 0

                    should_comment = (
                        comm_sets.enabled
                        and account_state.comments_sent_24h < comm_sets.daily_limit
                        and comm_sets.targets_file
                        and comm_sets.comments_file
                    )

                    time_spent_commenting = 0
                    if should_comment:
                        self.logger.info("Выполняем задачу комментирования...", username)
                        start_comm = time.time()
                        try:
                            with open(comm_sets.targets_file, 'r', encoding='utf-8') as f:
                                targets = [l.strip() for l in f if l.strip()]
                            with open(comm_sets.comments_file, 'r', encoding='utf-8') as f:
                                comments = [l.strip() for l in f if l.strip()]

                            if targets and comments:
                                target = random.choice(targets)
                                comment_text = random.choice(comments)
                                final_comment = generate_unique_message_from_raw(
                                    comment_text, processor=twitter_ops.leetspeak_processor, leetspeak_probability=0.1
                                )

                                photo_to_upload = None
                                if comm_sets.photo_path and os.path.exists(comm_sets.photo_path):
                                    if os.path.isdir(comm_sets.photo_path):
                                        images = [img for img in os.listdir(comm_sets.photo_path) if img.lower().endswith(('.png','.jpg','.jpeg'))]
                                        if images:
                                            photo_to_upload = os.path.join(comm_sets.photo_path, random.choice(images))
                                    else:
                                        photo_to_upload = comm_sets.photo_path

                                success = await twitter_ops.post_comment_with_photo(
                                    account_state.browser, target, final_comment, photo_to_upload, username, account_manager
                                )

                                if success:
                                    account_state.comments_sent_24h += 1
                                    account_state.last_comment_time = datetime.now()
                                    self.logger.info(f"Комментарий успешен! Всего сегодня: {account_state.comments_sent_24h}", username)
                        except Exception as e:
                            self.logger.error(f"Ошибка задачи комментирования: {e}", username)

                        time_spent_commenting = time.time() - start_comm

                    remaining_rest = rest_time_seconds - time_spent_commenting
                    if remaining_rest > 0:
                        self.logger.info(f"Отдыхаем оставшиеся {remaining_rest:.1f}с...", username)
                        await asyncio.sleep(remaining_rest)
                    else:
                        self.logger.info("Комментирование заняло больше времени, чем отдых. Начинаем следующий цикл сразу.", username)

            except asyncio.CancelledError:
                self.logger.info(f"Цикл рассылки для {username} был отменен.", username)
            except Exception as e:
                self.logger.error(f"Ошибка в цикле отправки: {type(e).__name__}: {str(e)}", username)
            finally:
                current = account_manager.accounts.get(username, account_state)
                current.is_mailing = False
                self.gui_update_callback()

    def start_account_cycle(self, account_state: AccountState, twitter_ops: TwitterOperations, account_manager: AccountManager, humanize: bool = True):
        with self.tasks_lock:
            if account_state.username in self.running_tasks:
                self.logger.warning("Задача отправки уже запущена для этого аккаунта", account_state.username)
                return
            
            async def wrapped_cycle():
                try:
                    await self.start_sending_cycle(account_state, twitter_ops, account_manager, humanize)
                except Exception as e:
                    self.logger.error(f"Критическая ошибка в цикле рассылки: {str(e)}", account_state.username)
                finally:
                    # Убедимся, что флаг сбрасывается даже при ошибке
                    account_state.is_mailing = False
                    # Удаляем из running_tasks
                    with self.tasks_lock:
                        if account_state.username in self.running_tasks:
                            del self.running_tasks[account_state.username]
                    # Обновляем GUI если коллбэк установлен
                    if self.gui_update_callback:
                        self.gui_update_callback()
            
            task = asyncio.create_task(wrapped_cycle())
            self.running_tasks[account_state.username] = task

    def stop_account_cycle(self, username: str):
        with self.tasks_lock:
            if username in self.running_tasks:
                # Set is_active to False to stop the loop
                if username in self.account_manager.accounts:
                    self.account_manager.accounts[username].is_active = False
                self.running_tasks[username].cancel()
                del self.running_tasks[username]
                self.logger.info(f"Остановлен цикл рассылки для {username}")
