"""
aiohttp-сервер веб-интерфейса: JSON API + WebSocket (живое состояние и логи) + статика.

Фазы приложения:
  setup — нет paths.json: пользователь указывает базовую папку;
  ready — движок создан, интерфейс работает.
"""
import asyncio
import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from xgenius import __version__
from xgenius.config import get_paths_from_base, read_saved_base_dir, save_base_dir
from xgenius.process_utils import force_kill_chromedrivers
from xgenius.settings import BROWSER_APP_MODE, OPEN_BROWSER, WEB_HOST, WEB_PORT
from xgenius.web.actions import ActionError, Actions
from xgenius.web.engine import Engine

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebApp:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.engine: Optional[Engine] = None
        self.actions: Optional[Actions] = None
        self.setup_message = ""
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle
    @property
    def phase(self) -> str:
        return "ready" if self.engine is not None else "setup"

    def start_engine(self) -> None:
        if self.engine is None:
            self.engine = Engine(self.loop)
            self.actions = Actions(self.engine)

    def state_payload(self) -> dict:
        if self.engine is not None:
            return self.engine.snapshot()
        base = read_saved_base_dir()
        return {
            "phase": "setup",
            "version": __version__,
            "base_dir": str(base) if base else "",
            "suggested_base_dir": str(Path.cwd() / "SoftTwitter"),
            "setup_message": self.setup_message,
        }

    async def shutdown(self):
        if self.engine is not None:
            try:
                await self.engine.shutdown()
            except Exception as e:
                print(f"shutdown error: {e}")
        self._stop.set()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _json(data: Any, status: int = 200) -> web.Response:
        return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False, default=str))

    def _require_engine(self) -> Actions:
        if self.actions is None:
            raise ActionError("Движок ещё не запущен: укажите базовую папку на экране Setup.")
        return self.actions

    @staticmethod
    def _usernames(body: dict) -> list:
        names = body.get("usernames") or ([body["username"]] if body.get("username") else [])
        if not names:
            raise ActionError("No accounts selected!")
        return list(dict.fromkeys(str(n) for n in names))

    # ------------------------------------------------------------------ handlers
    async def index(self, request):
        # Страница живёт в /static/, чтобы её относительные пути (style.css, app.js)
        # работали и при открытии файла напрямую, без сервера.
        raise web.HTTPFound("/static/index.html")

    async def api_state(self, request):
        return self._json(self.state_payload())

    async def api_setup(self, request):
        body = await request.json()
        raw = (body.get("base_dir") or "").strip()
        if not raw:
            raise ActionError("Укажите путь к базовой папке")
        base = Path(raw)
        if not base.exists():
            if body.get("create"):
                base.mkdir(parents=True, exist_ok=True)
            else:
                raise ActionError(f"Папка не найдена: {base}. Отметьте «создать», чтобы создать её.")
        chrome, driver = get_paths_from_base(base)
        warnings = []
        if not chrome.exists():
            warnings.append(f"Не найден {chrome}")
        if not driver.exists():
            warnings.append(f"Не найден {driver}")
        save_base_dir(base)
        self.setup_message = "; ".join(warnings)
        self.start_engine()
        return self._json({"ok": True, "warnings": warnings, "phase": self.phase})

    async def api_logs(self, request):
        if self.engine is None:
            return self._json({"seq": 0, "lines": []})
        seq, lines = self.engine.logs_since(int(request.query.get("since", "0")))
        return self._json({"seq": seq, "lines": lines})

    async def api_help(self, request):
        return web.FileResponse(STATIC_DIR / "help.txt")

    async def api_shutdown(self, request):
        self.loop.create_task(self.shutdown())
        return self._json({"ok": True})

    async def api_accounts_add(self, request):
        self._require_engine().add_account(await request.json())
        return self._json({"ok": True})

    async def api_accounts_import(self, request):
        added, skipped = self._require_engine().import_accounts((await request.json()).get("text", ""))
        return self._json({"ok": True, "added": added, "skipped": skipped})

    async def api_accounts_get(self, request):
        return self._json(self._require_engine().get_account(request.match_info["username"]))

    async def api_accounts_edit(self, request):
        self._require_engine().edit_account(request.match_info["username"], await request.json())
        return self._json({"ok": True})

    async def api_accounts_delete(self, request):
        body = await request.json()
        n = self._require_engine().delete(self._usernames(body))
        return self._json({"ok": True, "deleted": n})

    async def api_bulk_edit(self, request):
        body = await request.json()
        n = self._require_engine().bulk_edit(self._usernames(body), body.get("group"), body.get("proxies"))
        return self._json({"ok": True, "updated": n})

    async def api_action(self, request):
        """POST /api/actions/{name} — login, parse, mailing, pause, close, view, reset_errors, clear_groups, export_chats."""
        name = request.match_info["name"]
        body = await request.json() if request.can_read_body else {}
        a = self._require_engine()
        if name == "login":
            return self._json({"ok": True, "started": a.start_login(self._usernames(body))})
        if name == "parse":
            return self._json({"ok": True, "started": a.start_parse(self._usernames(body))})
        if name == "mailing":
            names = a.ready_usernames() if body.get("ready") else self._usernames(body)
            if not names:
                raise ActionError("No ready accounts: an account must be logged in, have messages and not be mailing already.")
            started, errors = a.start_mailing_many(names)
            return self._json({"ok": True, "started": started, "errors": errors})
        if name == "pause":
            paused, resumed = a.toggle_pause(self._usernames(body))
            return self._json({"ok": True, "paused": paused, "resumed": resumed})
        if name == "close":
            n = a.close_all() if body.get("all") else a.close(self._usernames(body))
            return self._json({"ok": True, "closed": n})
        if name == "view":
            await a.view(body.get("username", ""))
            return self._json({"ok": True})
        if name == "reset_errors":
            return self._json({"ok": True, "reset": a.reset_errors()})
        if name == "clear_groups":
            a.clear_groups(body.get("username", ""))
            return self._json({"ok": True})
        if name == "export_chats":
            path, content = a.export_chats(self._usernames(body))
            return self._json({"ok": True, "path": path, "content": content})
        raise ActionError(f"Unknown action: {name}")

    async def api_settings_get(self, request):
        return self._json(self._require_engine().get_settings(request.match_info["username"]))

    async def api_settings_put(self, request):
        body = await request.json()
        self._require_engine().save_settings(request.match_info["username"], body.get("cycle", {}), body.get("messages", []))
        return self._json({"ok": True})

    async def api_settings_mass(self, request):
        body = await request.json()
        n = self._require_engine().mass_settings(
            self._usernames(body), body.get("mode", "overwrite"), bool(body.get("update_settings", True)),
            bool(body.get("update_messages", True)), body.get("cycle", {}), body.get("messages", []))
        return self._json({"ok": True, "updated": n})

    async def api_comments_get(self, request):
        return self._json(self._require_engine().get_comment_settings(request.match_info["username"]))

    async def api_comments_put(self, request):
        self._require_engine().save_comment_settings(request.match_info["username"], await request.json())
        return self._json({"ok": True})

    async def api_stats_daily(self, request):
        return self._json(self._require_engine().daily_stats(request.match_info["username"]))

    async def api_stats_history(self, request):
        q = request.query
        return self._json(self._require_engine().history(q.get("from", ""), q.get("to", "")))

    async def api_stats_history_csv(self, request):
        q = request.query
        csv_text = self._require_engine().history_csv(q.get("from", ""), q.get("to", ""))
        fname = f"stats_{q.get('from', '')}_{q.get('to', '')}.csv"
        # utf-8-sig (BOM), чтобы Excel открыл кириллицу корректно — как в прежнем экспорте
        return web.Response(body=("﻿" + csv_text).encode("utf-8"), content_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    async def api_stats_delete(self, request):
        self._require_engine().delete_stats(request.match_info["username"])
        return self._json({"ok": True})

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        last_state = None
        last_seq = 0
        try:
            while not ws.closed and not self._stop.is_set():
                state = self.state_payload()
                encoded = json.dumps(state, ensure_ascii=False, default=str, sort_keys=True)
                if encoded != last_state:
                    await ws.send_str(json.dumps({"type": "state", "data": state}, ensure_ascii=False, default=str))
                    last_state = encoded
                if self.engine is not None:
                    seq, lines = self.engine.logs_since(last_seq)
                    if lines:
                        await ws.send_str(json.dumps({"type": "logs", "seq": seq, "lines": lines}, ensure_ascii=False))
                    last_seq = seq
                    await self.engine.wait_change(0.7)
                else:
                    await asyncio.sleep(0.7)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception as e:
            print(f"ws error: {e}")
        return ws

    # ------------------------------------------------------------------ app wiring
    @web.middleware
    async def errors_middleware(self, request, handler):
        try:
            return await handler(request)
        except ActionError as e:
            return self._json({"ok": False, "error": str(e)}, status=400)
        except web.HTTPException:
            raise
        except Exception as e:
            if self.engine is not None:
                self.engine.logger.error(f"API error {request.path}: {type(e).__name__}: {e}")
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)

    def build(self) -> web.Application:
        app = web.Application(middlewares=[self.errors_middleware], client_max_size=16 * 1024 * 1024)
        app.add_routes([
            web.get("/", self.index),
            web.get("/ws", self.ws_handler),
            web.get("/api/state", self.api_state),
            web.post("/api/setup", self.api_setup),
            web.get("/api/logs", self.api_logs),
            web.get("/api/help", self.api_help),
            web.post("/api/shutdown", self.api_shutdown),
            web.post("/api/accounts", self.api_accounts_add),
            web.post("/api/accounts/import", self.api_accounts_import),
            web.post("/api/accounts/delete", self.api_accounts_delete),
            web.post("/api/accounts/bulk_edit", self.api_bulk_edit),
            web.post("/api/settings/mass", self.api_settings_mass),
            web.get("/api/accounts/{username}", self.api_accounts_get),
            web.put("/api/accounts/{username}", self.api_accounts_edit),
            web.get("/api/accounts/{username}/settings", self.api_settings_get),
            web.put("/api/accounts/{username}/settings", self.api_settings_put),
            web.get("/api/accounts/{username}/comments", self.api_comments_get),
            web.put("/api/accounts/{username}/comments", self.api_comments_put),
            web.post("/api/actions/{name}", self.api_action),
            web.get("/api/stats/daily/{username}", self.api_stats_daily),
            web.get("/api/stats/history", self.api_stats_history),
            web.get("/api/stats/history.csv", self.api_stats_history_csv),
            web.delete("/api/stats/{username}", self.api_stats_delete),
            web.static("/static", STATIC_DIR),
        ])
        return app

    async def run_forever(self):
        if read_saved_base_dir() is not None:
            try:
                self.start_engine()
            except Exception as e:
                print(f"engine start failed, showing setup: {e}")
                self.setup_message = str(e)
        runner = web.AppRunner(self.build())
        await runner.setup()
        site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
        await site.start()
        url = f"http://{WEB_HOST}:{WEB_PORT}/"
        print(f"X-Genius {__version__} web UI: {url}")
        if OPEN_BROWSER:
            open_ui(url)
        try:
            await self._stop.wait()
        finally:
            await runner.cleanup()


def open_ui(url: str) -> None:
    """Открывает интерфейс: окно chrome --app (без адресной строки) из Bro/chrome.exe, иначе — браузер по умолчанию."""
    base = read_saved_base_dir()
    if BROWSER_APP_MODE and base is not None:
        chrome, _ = get_paths_from_base(base)
        if chrome.exists():
            try:
                profile = base / "webui_profile"
                subprocess.Popen([str(chrome), f"--app={url}", f"--user-data-dir={profile}",
                                  "--no-first-run", "--no-default-browser-check", "--window-size=1500,920"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception as e:
                print(f"chrome --app launch failed: {e}")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"browser open failed: {e}")


def serve() -> None:
    force_kill_chromedrivers()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = WebApp(loop)
    try:
        loop.run_until_complete(app.run_forever())
    except KeyboardInterrupt:
        print("Application terminated by user")
        try:
            loop.run_until_complete(app.shutdown())
        except Exception:
            pass
    finally:
        print("Final cleanup...")
        force_kill_chromedrivers()
        loop.close()
        sys.exit(0)
