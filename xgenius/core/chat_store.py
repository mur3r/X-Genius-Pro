"""
ChatStore — группы аккаунта: кеш, очередь обхода, страйки, отключённые группы.
"""
import json
import random
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .page_state import SUCCESS, NO_INPUT

# Сколько раз группа должна дать NO_INPUT, прежде чем мы её временно отключим.
NO_INPUT_STRIKES_TO_DISABLE = 3
# Сколько подряд RETRY по одной группе, прежде чем отключить её как "битую".
RETRY_STRIKES_TO_DISABLE = 6
# Через сколько часов отключённую группу пробуем снова (страйки сбрасываются).
DISABLED_TTL_HOURS = 24


class ChatStore:
    """
    Хранит для каждого аккаунта:
      cache  — все известные ссылки на группы (никогда не удаляются автоматически);
      queue  — порядок обхода в текущем проходе;
      state  — по каждой группе: страйки NO_INPUT / RETRY, отметка об отключении.

    Файлы chat_cache.json / chat_queue.json сохраняют старый формат (совместимость),
    страйки живут в chat_state.json. Все записи атомарные и под RLock, данные держим
    в памяти — раньше каждый next_chat читал и переписывал оба файла целиком.
    """

    def __init__(self, base_dir: Path, logger=None):
        self.base_dir = Path(base_dir)
        self.cache_file = self.base_dir / "chat_cache.json"
        self.queue_file = self.base_dir / "chat_queue.json"
        self.state_file = self.base_dir / "chat_state.json"
        self.logger = logger
        self._lock = threading.RLock()
        self._cache: Dict[str, List[str]] = {}
        self._queue: Dict[str, List[str]] = {}
        self._state: Dict[str, Dict[str, dict]] = {}
        self._load()

    # ---------- IO ----------
    def _read_json(self, path: Path) -> dict:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    return raw
        except Exception as e:
            self._log(f"ChatStore: не удалось прочитать {path.name}: {e}")
        return {}

    def _load(self):
        with self._lock:
            self._cache = {u: self._dedupe(v) for u, v in self._read_json(self.cache_file).items()}
            self._queue = {u: self._dedupe(v) for u, v in self._read_json(self.queue_file).items()}
            st = self._read_json(self.state_file)
            self._state = {u: v for u, v in st.items() if isinstance(v, dict)}

    def _write_atomic(self, path: Path, data):
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)

    def _save(self):
        with self._lock:
            try:
                self._write_atomic(self.cache_file, self._cache)
                self._write_atomic(self.queue_file, self._queue)
                self._write_atomic(self.state_file, self._state)
            except Exception as e:
                self._log(f"ChatStore: ошибка записи: {e}")

    @staticmethod
    def _dedupe(items) -> List[str]:
        if not isinstance(items, list):
            return []
        return list(dict.fromkeys(str(x).strip() for x in items if x))

    def _log(self, msg: str, username: Optional[str] = None):
        if self.logger is not None:
            try:
                self.logger.warning(msg, username)
            except Exception:
                pass

    # ---------- чтение ----------
    def all_groups(self, username: str) -> List[str]:
        with self._lock:
            return list(self._cache.get(username, []))

    def group_state(self, username: str, group: str) -> dict:
        with self._lock:
            return dict(self._state.get(username, {}).get(group, {}))

    def _is_disabled(self, st: dict, now: float) -> bool:
        at = st.get("disabled_at")
        if not at:
            return False
        if now - float(at) >= DISABLED_TTL_HOURS * 3600:
            # TTL истёк — даём группе ещё один шанс
            st.pop("disabled_at", None)
            st["no_input"] = 0
            st["retry"] = 0
            return False
        return True

    def enabled_groups(self, username: str, now: Optional[float] = None) -> List[str]:
        now = now if now is not None else time.time()
        with self._lock:
            ust = self._state.setdefault(username, {})
            return [g for g in self._cache.get(username, []) if not self._is_disabled(ust.setdefault(g, {}), now)]

    def disabled_groups(self, username: str, now: Optional[float] = None) -> Dict[str, dict]:
        now = now if now is not None else time.time()
        with self._lock:
            ust = self._state.get(username, {})
            return {g: dict(st) for g, st in ust.items() if self._is_disabled(st, now)}

    def queue_len(self, username: str) -> int:
        with self._lock:
            return len(self._queue.get(username, []))

    # ---------- запись ----------
    def merge_parsed(self, username: str, found) -> Tuple[List[str], int]:
        """
        Объединяет свежий результат парсинга с кешем. НИЧЕГО не удаляет:
        неполный проход по списку чатов (X подгружает лениво) раньше стирал группы.
        Возвращает (все группы, сколько новых добавлено).
        """
        found = self._dedupe(sorted(set(found or [])))
        with self._lock:
            cache = self._cache.setdefault(username, [])
            queue = self._queue.setdefault(username, [])
            known = set(cache)
            added = 0
            for g in found:
                if g not in known:
                    cache.append(g)
                    known.add(g)
                    queue.append(g)
                    added += 1
            self._save()
            return list(cache), added

    def replace_groups(self, username: str, groups) -> None:
        """Явная замена списка (используется только по прямому действию пользователя)."""
        with self._lock:
            self._cache[username] = self._dedupe(list(groups))
            self._queue[username] = [g for g in self._queue.get(username, []) if g in self._cache[username]]
            self._save()

    def next_chat(self, username: str, now: Optional[float] = None) -> Optional[str]:
        """Достаёт следующую группу из очереди; пустую очередь наполняет заново
        (случайный порядок) из включённых групп."""
        now = now if now is not None else time.time()
        with self._lock:
            enabled = set(self.enabled_groups(username, now))
            if not enabled:
                return None
            queue = [g for g in self._queue.get(username, []) if g in enabled]
            if not queue:
                queue = list(enabled)
                random.shuffle(queue)
            selected = queue.pop(0)
            self._queue[username] = queue
            self._save()
            return selected

    def report(self, username: str, group: str, outcome: str, reason: str = "",
               now: Optional[float] = None) -> Optional[str]:
        """
        Учитывает результат отправки. Возвращает 'disabled', если группа была
        отключена, иначе None.
          SUCCESS   — сброс страйков;
          RETRY     — группа возвращается в конец очереди, retry += 1;
          NO_INPUT  — no_input += 1, группа в конец очереди; после N страйков — отключение.
        """
        now = now if now is not None else time.time()
        with self._lock:
            ust = self._state.setdefault(username, {})
            st = ust.setdefault(group, {})
            queue = self._queue.setdefault(username, [])
            event = None
            if outcome == SUCCESS:
                st["no_input"] = 0
                st["retry"] = 0
                st["last_ok"] = now
                st.pop("disabled_at", None)
                st.pop("reason", None)
            elif outcome == NO_INPUT:
                st["no_input"] = int(st.get("no_input", 0)) + 1
                st["last_error"] = reason
                st["last_error_at"] = now
                if st["no_input"] >= NO_INPUT_STRIKES_TO_DISABLE:
                    st["disabled_at"] = now
                    st["reason"] = f"no composer x{st['no_input']}: {reason}"
                    event = "disabled"
                elif group not in queue:
                    queue.append(group)
            else:  # RETRY / FAILED / всё остальное временное
                st["retry"] = int(st.get("retry", 0)) + 1
                st["last_error"] = reason
                st["last_error_at"] = now
                if st["retry"] >= RETRY_STRIKES_TO_DISABLE:
                    st["disabled_at"] = now
                    st["reason"] = f"persistent errors x{st['retry']}: {reason}"
                    event = "disabled"
                elif group not in queue:
                    queue.append(group)
            self._save()
            return event

    def requeue(self, username: str, group: str) -> None:
        """Вернуть группу в конец очереди без учёта страйков (релогин, пауза и т.п.)."""
        with self._lock:
            queue = self._queue.setdefault(username, [])
            if group in self._cache.get(username, []) and group not in queue:
                queue.append(group)
                self._save()

    def enable(self, username: str, group: str) -> None:
        with self._lock:
            st = self._state.setdefault(username, {}).setdefault(group, {})
            st.pop("disabled_at", None)
            st["no_input"] = 0
            st["retry"] = 0
            self._save()

    def remove_user(self, username: str) -> None:
        with self._lock:
            self._cache.pop(username, None)
            self._queue.pop(username, None)
            self._state.pop(username, None)
            self._save()
