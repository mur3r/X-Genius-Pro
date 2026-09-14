"""
Мониторинг нагрузки сервера: CPU по ядрам, RAM, процессы Chrome с разбивкой по аккаунтам,
пул потоков Selenium (сколько вызовов в работе, их длительность), лаг event loop.

Зачем: при 50+ браузерах на сервере без GPU нужно видеть, ЧТО именно упирается —
ядра (Chrome-рендеринг), потоки Python (все 128 заняты, вызовы к chromedriver стоят в
очереди), или сам event loop (кто-то блокирует цикл). Без этого «программа медленно
набирает сообщение» и «аккаунт X работает хуже других» объяснить нельзя.

Куда пишет:
  logs/sysmon_YYYYMMDD.csv          — одна строка на замер (SYSMON_INTERVAL с);
  logs/sysmon_accounts_YYYYMMDD.csv — разбивка по аккаунтам (SYSMON_ACCOUNTS_EVERY с);
  основной bot_YYYYMMDD.log         — строка [SYSMON] раз в SYSMON_LOG_EVERY с (пульс: пропуск
                                      строк = программа висела или не работала);
  веб-интерфейс                     — вкладка Load (живые данные + история за SYSMON_HISTORY_MINUTES).
"""
import asyncio
import csv
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from xgenius.core import classify_chrome_process, heartbeat_line
from xgenius.settings import (
    SYSMON_ACCOUNTS_EVERY,
    SYSMON_HISTORY_MINUTES,
    SYSMON_INTERVAL,
    SYSMON_LOG_EVERY,
)

CSV_COLUMNS = [
    "ts", "cpu", "cpu_user", "cpu_sys", "cpu_max_core", "cores_over_90", "load1",
    "mem_used_gb", "mem_pct",
    "chrome_procs", "chrome_threads", "chrome_cpu_raw", "chrome_cpu", "chrome_rss_gb",
    "chrome_other_procs", "chrome_other_cpu",
    "py_cpu", "py_rss_mb", "py_threads",
    "exec_max", "exec_threads", "exec_inflight", "sel_calls", "sel_avg_ms", "sel_max_ms",
    "loop_lag_ms", "browsers", "mailing", "parsing", "per_core",
]
ACCOUNTS_CSV_COLUMNS = ["ts", "username", "phase", "procs", "threads", "cpu_raw", "cpu", "rss_mb"]


class CountingExecutor(ThreadPoolExecutor):
    """
    ThreadPoolExecutor, который считает вызовы Selenium: сколько сейчас в работе (включая
    ожидающие свободный поток), сколько выполнено с прошлого замера и как долго они шли.
    Средняя/максимальная длительность вызова — прямой показатель «chromedriver отвечает
    медленно», а inflight == max_workers — «потоков не хватает, вызовы стоят в очереди».
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._xg_lock = threading.Lock()
        self.inflight = 0
        self._calls = 0
        self._sum_ms = 0.0
        self._max_ms = 0.0

    def submit(self, fn, *args, **kwargs):
        def wrapped(*a, **k):
            t0 = time.monotonic()
            try:
                return fn(*a, **k)
            finally:
                ms = (time.monotonic() - t0) * 1000.0
                with self._xg_lock:
                    self.inflight -= 1
                    self._calls += 1
                    self._sum_ms += ms
                    if ms > self._max_ms:
                        self._max_ms = ms

        with self._xg_lock:
            self.inflight += 1
        try:
            return super().submit(wrapped, *args, **kwargs)
        except BaseException:
            with self._xg_lock:
                self.inflight -= 1
            raise

    def stats(self, reset: bool = True) -> Dict[str, Any]:
        with self._xg_lock:
            calls, s, m, inflight = self._calls, self._sum_ms, self._max_ms, self.inflight
            if reset:
                self._calls, self._sum_ms, self._max_ms = 0, 0.0, 0.0
        threads = len(getattr(self, "_threads", ()) or ())
        return {
            "max": self._max_workers,
            "threads": threads,
            "inflight": inflight,
            "calls": calls,
            "avg_ms": round(s / calls, 1) if calls else None,
            "max_ms": round(m, 1) if calls else None,
        }


class SystemMonitor:
    def __init__(self, engine, executor: Optional[CountingExecutor]):
        self.engine = engine
        self.config = engine.config
        self.logger = engine.logger
        self.executor = executor
        self.interval = max(1, int(SYSMON_INTERVAL or 0)) if SYSMON_INTERVAL else 0
        self.enabled = self.interval > 0
        self.seq = 0
        self.latest: Dict[str, Any] = {}
        maxlen = max(10, int(SYSMON_HISTORY_MINUTES * 60 / (self.interval or 5)))
        self.history: deque = deque(maxlen=maxlen)

        self._profiles_marker = str(self.config.browser_profiles_dir)
        self._webui_marker = str(self.config.base_dir / "webui_profile")
        self._procs: Dict[int, Dict[str, Any]] = {}   # pid -> {p, ct, ours, account, role}
        self._self = psutil.Process(os.getpid())
        self._own_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sysmon")
        self._lag_max_ms = 0.0
        self._last_log = 0.0
        self._last_accounts_csv = 0.0
        self._warned: Dict[str, float] = {}
        self._cpu_hot_streak = 0
        self.info = {
            "cpu_count": psutil.cpu_count(logical=True) or 1,
            "cpu_physical": psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 1,
            "mem_total_gb": round(psutil.virtual_memory().total / 2 ** 30, 1),
            "interval": self.interval,
            "history_minutes": SYSMON_HISTORY_MINUTES,
            "csv": str(self._csv_path()),
            "accounts_csv": str(self._accounts_csv_path()),
        }
        # Первый вызов cpu_percent всегда возвращает 0 — «прогреваем»
        try:
            psutil.cpu_percent(percpu=True)
            psutil.cpu_times_percent()
            self._self.cpu_percent()
        except Exception:
            pass

    # ------------------------------------------------------------------ файлы
    def _csv_path(self) -> Path:
        return self.config.logs_dir / f"sysmon_{datetime.now().strftime('%Y%m%d')}.csv"

    def _accounts_csv_path(self) -> Path:
        return self.config.logs_dir / f"sysmon_accounts_{datetime.now().strftime('%Y%m%d')}.csv"

    @staticmethod
    def _append_csv(path: Path, columns: List[str], rows: List[Dict[str, Any]]) -> None:
        new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            if new:
                w.writeheader()
            for r in rows:
                w.writerow(r)

    # ------------------------------------------------------------------ замер (в отдельном потоке)
    def _account_phases(self) -> Dict[str, str]:
        phases: Dict[str, str] = {}
        am = self.engine.account_manager
        for u, st in list(am.accounts.items()):
            if st.is_paused:
                phases[u] = "paused"
            elif st.is_parsing:
                phases[u] = "parsing"
            elif st.is_mailing:
                phases[u] = "mailing"
            elif st.relogin_in_progress:
                phases[u] = "relogin"
            elif st.is_active:
                phases[u] = "idle"
            elif st.browser:
                phases[u] = "browser"
            else:
                phases[u] = "inactive"
        return phases

    def _scan_chrome(self) -> Dict[str, Any]:
        """Проходит по процессам chrome/chromedriver, считает CPU/RSS/потоки и группирует по аккаунтам."""
        seen = set()
        per_account: Dict[str, Dict[str, Any]] = {}
        ours = {"procs": 0, "threads": 0, "cpu_raw": 0.0, "rss": 0}
        other = {"procs": 0, "cpu_raw": 0.0}
        for p in psutil.process_iter(["name", "create_time"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "chrome" not in name:
                    continue
                pid = p.pid
                rec = self._procs.get(pid)
                if rec is None or rec["ct"] != p.info.get("create_time"):
                    # Новый процесс (или pid переиспользован): читаем командную строку один раз
                    try:
                        cmd = " ".join(p.cmdline())
                    except (psutil.AccessDenied, psutil.ZombieProcess):
                        cmd = ""
                    cls = classify_chrome_process(name, cmd, self._profiles_marker, self._webui_marker)
                    if cls["role"] == "driver" and not cls["ours"]:
                        # chromedriver.exe без --user-data-dir: наш, если запущен этим процессом Python
                        try:
                            if p.ppid() == os.getpid():
                                cls = {"ours": True, "account": "_driver", "role": "driver"}
                        except Exception:
                            pass
                    rec = {"p": p, "ct": p.info.get("create_time"), **cls}
                    try:
                        p.cpu_percent(None)  # прогрев: первый вызов = 0
                    except Exception:
                        pass
                    self._procs[pid] = rec
                seen.add(pid)
                proc = rec["p"]
                with proc.oneshot():
                    cpu = proc.cpu_percent(None)
                    if not rec["ours"]:
                        other["procs"] += 1
                        other["cpu_raw"] += cpu
                        continue
                    rss = proc.memory_info().rss
                    try:
                        thr = proc.num_threads()
                    except Exception:
                        thr = 0
                ours["procs"] += 1
                ours["threads"] += thr
                ours["cpu_raw"] += cpu
                ours["rss"] += rss
                acc = per_account.setdefault(rec["account"], {"procs": 0, "threads": 0, "cpu_raw": 0.0, "rss": 0})
                acc["procs"] += 1
                acc["threads"] += thr
                acc["cpu_raw"] += cpu
                acc["rss"] += rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        for pid in list(self._procs.keys()):
            if pid not in seen:
                del self._procs[pid]
        return {"ours": ours, "other": other, "accounts": per_account}

    def _sample_sync(self) -> Dict[str, Any]:
        ncpu = self.info["cpu_count"]
        cores = psutil.cpu_percent(percpu=True)
        total = round(sum(cores) / max(1, len(cores)), 1)
        try:
            tp = psutil.cpu_times_percent()
            user, system = round(tp.user, 1), round(getattr(tp, "system", 0.0), 1)
        except Exception:
            user, system = None, None
        try:
            load1 = round(psutil.getloadavg()[0], 2)
        except Exception:
            load1 = None
        vm = psutil.virtual_memory()

        try:
            with self._self.oneshot():
                py_cpu = self._self.cpu_percent(None)
                py_rss = self._self.memory_info().rss
                py_threads = self._self.num_threads()
        except Exception:
            py_cpu, py_rss, py_threads = 0.0, 0, threading.active_count()

        scan = self._scan_chrome()
        ours, other = scan["ours"], scan["other"]
        phases = self._account_phases()

        accounts = []
        for name, a in scan["accounts"].items():
            accounts.append({
                "username": name,
                "phase": phases.get(name, {"_webui": "webui", "_driver": "driver"}.get(name, "unknown")),
                "procs": a["procs"],
                "threads": a["threads"],
                "cpu_raw": round(a["cpu_raw"], 1),
                "cpu": round(a["cpu_raw"] / ncpu, 2),
                "rss_mb": round(a["rss"] / 2 ** 20),
            })
        # Аккаунты без процессов Chrome, но с состоянием — тоже показываем (браузера нет)
        for u, ph in phases.items():
            if u not in scan["accounts"] and ph not in ("inactive",):
                accounts.append({"username": u, "phase": ph, "procs": 0, "threads": 0, "cpu_raw": 0.0, "cpu": 0.0, "rss_mb": 0})
        accounts.sort(key=lambda r: (-r["cpu_raw"], r["username"]))

        ex = self.executor.stats(reset=True) if self.executor is not None else {
            "max": None, "threads": None, "inflight": None, "calls": 0, "avg_ms": None, "max_ms": None}
        lag = round(self._lag_max_ms, 1)
        self._lag_max_ms = 0.0

        am = self.engine.account_manager
        browsers = sum(1 for st in am.accounts.values() if st.browser)
        now = datetime.now()
        return {
            "t": time.time(),
            "ts": now.strftime("%H:%M:%S"),
            "cpu": {
                "total": total, "user": user, "system": system,
                "cores": [round(c) for c in cores], "max_core": round(max(cores) if cores else 0),
                "busy_cores": sum(1 for c in cores if c >= 90), "count": ncpu,
                "physical": self.info["cpu_physical"], "load1": load1,
            },
            "mem": {
                "total_gb": round(vm.total / 2 ** 30, 1), "used_gb": round((vm.total - vm.available) / 2 ** 30, 1),
                "avail_gb": round(vm.available / 2 ** 30, 1), "pct": round(vm.percent, 1),
            },
            "chrome": {
                "procs": ours["procs"], "threads": ours["threads"],
                "cpu_raw": round(ours["cpu_raw"], 1), "cpu": round(ours["cpu_raw"] / ncpu, 1),
                "rss_gb": round(ours["rss"] / 2 ** 30, 2),
                "other_procs": other["procs"], "other_cpu": round(other["cpu_raw"] / ncpu, 1),
            },
            "python": {"cpu": round(py_cpu / ncpu, 1), "cpu_raw": round(py_cpu, 1),
                       "rss_mb": round(py_rss / 2 ** 20), "threads": py_threads},
            "executor": ex,
            "loop_lag_ms": lag,
            "engine": {
                "browsers": browsers,
                "mailing": sum(1 for p in phases.values() if p == "mailing"),
                "parsing": sum(1 for p in phases.values() if p == "parsing"),
                "idle": sum(1 for p in phases.values() if p == "idle"),
            },
            "accounts": accounts,
        }

    def _write_files(self, s: Dict[str, Any]) -> None:
        cpu, mem, ch, py, ex, en = s["cpu"], s["mem"], s["chrome"], s["python"], s["executor"], s["engine"]
        row = {
            "ts": datetime.fromtimestamp(s["t"]).strftime("%Y-%m-%d %H:%M:%S"),
            "cpu": cpu["total"], "cpu_user": cpu["user"], "cpu_sys": cpu["system"], "cpu_max_core": cpu["max_core"],
            "cores_over_90": cpu["busy_cores"], "load1": cpu["load1"],
            "mem_used_gb": mem["used_gb"], "mem_pct": mem["pct"],
            "chrome_procs": ch["procs"], "chrome_threads": ch["threads"], "chrome_cpu_raw": ch["cpu_raw"],
            "chrome_cpu": ch["cpu"], "chrome_rss_gb": ch["rss_gb"],
            "chrome_other_procs": ch["other_procs"], "chrome_other_cpu": ch["other_cpu"],
            "py_cpu": py["cpu"], "py_rss_mb": py["rss_mb"], "py_threads": py["threads"],
            "exec_max": ex.get("max"), "exec_threads": ex.get("threads"), "exec_inflight": ex.get("inflight"),
            "sel_calls": ex.get("calls"), "sel_avg_ms": ex.get("avg_ms"), "sel_max_ms": ex.get("max_ms"),
            "loop_lag_ms": s["loop_lag_ms"], "browsers": en["browsers"], "mailing": en["mailing"],
            "parsing": en["parsing"], "per_core": "|".join(str(c) for c in cpu["cores"]),
        }
        path = self._csv_path()
        self.info["csv"] = str(path)  # после полуночи файл новый
        self._append_csv(path, CSV_COLUMNS, [row])

        if SYSMON_ACCOUNTS_EVERY and s["t"] - self._last_accounts_csv >= SYSMON_ACCOUNTS_EVERY:
            self._last_accounts_csv = s["t"]
            rows = [dict(a, ts=row["ts"]) for a in s["accounts"] if a["procs"]]
            if rows:
                apath = self._accounts_csv_path()
                self.info["accounts_csv"] = str(apath)
                self._append_csv(apath, ACCOUNTS_CSV_COLUMNS, rows)

    # ------------------------------------------------------------------ предупреждения в лог
    def _warn_once(self, key: str, message: str, every: float = 300.0) -> None:
        now = time.time()
        if now - self._warned.get(key, 0.0) < every:
            return
        self._warned[key] = now
        self.logger.warning(message)

    def _check_pressure(self, s: Dict[str, Any]) -> None:
        cpu, ex, mem = s["cpu"], s["executor"], s["mem"]
        if cpu["total"] >= 95:
            self._cpu_hot_streak += 1
        else:
            self._cpu_hot_streak = 0
        if self._cpu_hot_streak >= 3:
            self._warn_once("cpu", (
                f"[SYSMON] CPU насыщен: {cpu['total']:.0f}% уже {self._cpu_hot_streak * self.interval} с, "
                f"Chrome даёт {s['chrome']['cpu']:.0f}%. Команды chromedriver будут отвечать медленно: "
                f"ср. {ex.get('avg_ms') or 0:.0f} мс, макс {ex.get('max_ms') or 0:.0f} мс за последний замер."))
        if ex.get("max") and ex.get("inflight") is not None and ex["inflight"] >= ex["max"]:
            self._warn_once("exec", (
                f"[SYSMON] Все {ex['max']} потоков Selenium заняты, вызовы стоят в очереди. "
                f"Увеличьте EXECUTOR_MAX_WORKERS или уменьшите число одновременных аккаунтов."))
        if (ex.get("max_ms") or 0) >= 15000:
            self._warn_once("slow", (
                f"[SYSMON] Есть вызовы chromedriver дольше 15 с (макс {ex['max_ms'] / 1000:.0f} с). "
                f"Это либо прокси/загрузка страницы, либо перегруженный CPU — см. вкладку Load."))
        if s["loop_lag_ms"] >= 1000:
            self._warn_once("lag", (
                f"[SYSMON] Event loop задерживается на {s['loop_lag_ms'] / 1000:.1f} с — что-то блокирует цикл "
                f"(синхронный вызов Selenium вне executor или нехватка CPU процессу Python)."))
        if mem["pct"] >= 90:
            self._warn_once("mem", f"[SYSMON] RAM занята на {mem['pct']:.0f}% ({mem['used_gb']:.0f}/{mem['total_gb']:.0f} GB).")

    # ------------------------------------------------------------------ задачи
    async def _lag_ticker(self) -> None:
        """Раз в секунду замеряет, насколько поздно проснулся sleep(1) — это и есть лаг event loop."""
        loop = asyncio.get_event_loop()
        while True:
            t0 = loop.time()
            await asyncio.sleep(1.0)
            lag_ms = (loop.time() - t0 - 1.0) * 1000.0
            if lag_ms > self._lag_max_ms:
                self._lag_max_ms = lag_ms

    async def run(self) -> None:
        if not self.enabled:
            self.logger.info("[SYSMON] мониторинг нагрузки выключен (SYSMON_INTERVAL=0)")
            return
        self.logger.info(
            f"[SYSMON] мониторинг нагрузки: {self.info['cpu_physical']} ядер / {self.info['cpu_count']} потоков, "
            f"RAM {self.info['mem_total_gb']} GB; замер каждые {self.interval} с → {self.info['csv']}")
        loop = asyncio.get_event_loop()
        ticker = loop.create_task(self._lag_ticker())
        try:
            while True:
                await asyncio.sleep(self.interval)
                try:
                    s = await loop.run_in_executor(self._own_pool, self._sample_sync)
                except Exception as e:
                    self.logger.warning(f"[SYSMON] замер не удался: {type(e).__name__}: {e}")
                    continue
                self.seq += 1
                s["seq"] = self.seq
                self.latest = s
                self.history.append({
                    "t": s["t"], "cpu": s["cpu"]["total"], "chrome": s["chrome"]["cpu"], "mem": s["mem"]["pct"],
                    "lag": s["loop_lag_ms"], "sel_avg": s["executor"].get("avg_ms"),
                    "sel_max": s["executor"].get("max_ms"), "inflight": s["executor"].get("inflight"),
                    "browsers": s["engine"]["browsers"],
                })
                try:
                    await loop.run_in_executor(self._own_pool, self._write_files, s)
                except Exception as e:
                    self.logger.warning(f"[SYSMON] не удалось записать CSV: {e}")
                if SYSMON_LOG_EVERY and s["t"] - self._last_log >= SYSMON_LOG_EVERY:
                    self._last_log = s["t"]
                    self.logger.info(heartbeat_line(s))
                self._check_pressure(s)
                self.engine.notify()
        except asyncio.CancelledError:
            pass
        finally:
            ticker.cancel()
            self._own_pool.shutdown(wait=False)

    # ------------------------------------------------------------------ для API
    def payload(self) -> Dict[str, Any]:
        return {"info": self.info, "enabled": self.enabled, "latest": self.latest, "history": list(self.history)}
