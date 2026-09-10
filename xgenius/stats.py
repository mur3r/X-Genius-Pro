"""
Статистика сообщений / ретвитов / комментариев (JSON, атомарная запись).
"""

import json
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from xgenius.config import Config


# --------------------- StatsManager (Fixed and Optimized) ---------------------
class StatsManager:
    def __init__(self, config: Config):
        self.msg_stats_file = config.sending_stats_file
        self.rt_stats_file = config.retweet_stats_file
        self.comm_stats_file = config.comm_stats_file
        self._lock = threading.Lock()
        
        self.msg_data: Dict[str, List[float]] = self._load_stats(self.msg_stats_file)
        self.rt_data: Dict[str, List[float]] = self._load_stats(self.rt_stats_file)
        self.comm_data: Dict[str, List[float]] = self._load_stats(self.comm_stats_file)

    def _load_stats(self, filepath: Path) -> Dict[str, List[float]]:
        try:
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {k.lower(): v for k, v in data.items()}
        except (json.JSONDecodeError, IOError):
            pass
            
        return {}

    def _save_stats(self, filepath: Path, data: Dict[str, List[float]]) -> None:
        """
        Использует атомарную запись: пишет во временный файл, а затем переименовывает.
        Это предотвращает повреждение файла при сбое программы.
        """
        temp_file = filepath.with_suffix('.tmp')
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            
            # Atomic rename (replace)
            shutil.move(str(temp_file), str(filepath))
        except Exception as e:
            print(f"Error saving stats to {filepath}: {e}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except:
                    pass

    def record_message_sent(self, username: str) -> None:
        username = username.lower().strip() # Normalize
        with self._lock:
            timestamp = datetime.now().timestamp()
            if username not in self.msg_data: self.msg_data[username] = []
            self.msg_data[username].append(timestamp)
            self._save_stats(self.msg_stats_file, self.msg_data)

    def record_retweet(self, username: str) -> None:
        username = username.lower().strip() # Normalize
        with self._lock:
            timestamp = datetime.now().timestamp()
            if username not in self.rt_data: self.rt_data[username] = []
            self.rt_data[username].append(timestamp)
            self._save_stats(self.rt_stats_file, self.rt_data)

    def record_comment(self, username: str) -> None:
        username = username.lower().strip() # Normalize
        with self._lock:
            timestamp = datetime.now().timestamp()
            if username not in self.comm_data: self.comm_data[username] = []
            self.comm_data[username].append(timestamp)
            self._save_stats(self.comm_stats_file, self.comm_data)

    def delete_stats_for_user(self, username: str) -> None:
        username = username.lower().strip()
        with self._lock:
            if username in self.msg_data: del self.msg_data[username]
            if username in self.rt_data: del self.rt_data[username]
            if username in self.comm_data: del self.comm_data[username]
            
            self._save_stats(self.msg_stats_file, self.msg_data)
            self._save_stats(self.rt_stats_file, self.rt_data)
            self._save_stats(self.comm_stats_file, self.comm_data)

    def get_stats_for_24h(self, username: str) -> int:
        username = username.lower().strip()
        with self._lock:
            if username not in self.msg_data: return 0
            now = datetime.now()
            twenty_four_hours_ago = (now - timedelta(hours=24)).timestamp()
            recent = [ts for ts in self.msg_data[username] if ts > twenty_four_hours_ago]
            return len(recent)

    def get_retweets_24h_count(self, username: str) -> int:
        username = username.lower().strip()
        with self._lock:
            if username not in self.rt_data: return 0
            now = datetime.now()
            twenty_four_hours_ago = (now - timedelta(hours=24)).timestamp()
            recent = [ts for ts in self.rt_data[username] if ts > twenty_four_hours_ago]
            return len(recent)

    def get_detailed_stats(self, start_date: datetime, end_date: datetime) -> List[dict]:
        result = []
        
        # Ensure we cover the full range of timestamps
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()

        with self._lock:
            all_users = set(self.msg_data.keys()) | set(self.rt_data.keys()) | set(self.comm_data.keys())
            
            for username in all_users:
                msgs = self.msg_data.get(username, [])
                rts = self.rt_data.get(username, [])
                comms = self.comm_data.get(username, [])

                msgs_in = len([ts for ts in msgs if start_ts <= ts <= end_ts])
                rts_in = len([ts for ts in rts if start_ts <= ts <= end_ts])
                comms_in = len([ts for ts in comms if start_ts <= ts <= end_ts])
                
                # Show if there is ANY activity in period OR total history
                if msgs_in > 0 or rts_in > 0 or comms_in > 0 or len(msgs) > 0 or len(rts) > 0:
                     result.append({
                        "username": username,
                        "msg_period": msgs_in,
                        "rt_period": rts_in,
                        "comm_period": comms_in,
                        "msg_total": len(msgs),
                        "rt_total": len(rts),
                        "comm_total": len(comms)
                    })
        return result

    def clear_all_stats(self) -> None:
        """Очищает всю статистику"""
        with self._lock:
            self.msg_data = {}
            self.rt_data = {}
            self.comm_data = {}
            
            self._save_stats(self.msg_stats_file, self.msg_data)
            self._save_stats(self.rt_stats_file, self.rt_data)
            self._save_stats(self.comm_stats_file, self.comm_data)
