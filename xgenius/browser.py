"""
Создание Chrome: флаги против нагрузки, прокси-расширение, stealth, CDP-блокировка медиа.
"""

import asyncio
import random
import zipfile

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium_stealth import stealth

from xgenius.config import Config
from xgenius.models import AccountCredentials, BrowserConfig
from xgenius.settings import BLOCK_MEDIA_URLS


# Размер экрана нужен для позиционирования окон Chrome (без tkinter: WinAPI на Windows)
def _screen_size():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


SCREEN_WIDTH, SCREEN_HEIGHT = _screen_size()

# --------------------- BrowserManager ---------------------
class BrowserManager:
    def __init__(self, config: Config, browser_config: BrowserConfig):
        self.config = config
        self.browser_config = browser_config

    async def create_browser(self, credentials: AccountCredentials) -> webdriver.Chrome:
        try:
            chrome_bin = self.config.chrome_path
            driver_path = self.config.chromedriver_path
            options = Options()
            options.binary_location = str(chrome_bin)

            # 1. Возвращаем стандартную стратегию, чтобы React успевал отрендерить элементы
            options.page_load_strategy = "normal"

            # 2. Флаги, снимающие фоновую нагрузку с CPU (сервер без видеокарты:
            #    всё, что анимируется/проигрывается, рендерится процессором).
            options.add_argument("--disable-gpu")
            options.add_argument("--mute-audio")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--no-first-run")
            options.add_argument("--disable-dev-shm-usage") # Обязательно для экономии RAM
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-component-update")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-default-apps")
            options.add_argument("--disable-client-side-phishing-detection")
            options.add_argument("--metrics-recording-only")
            options.add_argument("--log-level=3")
            # Видео в ленте/чатах не стартует само — самый большой пожиратель CPU без GPU
            options.add_argument("--autoplay-policy=user-gesture-required")
            options.add_argument("--disable-features=Translate,MediaRouter,OptimizationHints,InterestFeedContentSuggestions,BackForwardCache")

            prefs = {
                # Картинки оставляем (их отключение не ломает React, но операторы хотят видеть чаты)
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.geolocation": 2,
                "profile.default_content_settings.popups": 0,
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
            }
            options.add_experimental_option("prefs", prefs)

            # 3. Увеличиваем ширину окна до десктопного брейкпоинта (минимум 1024px)
            user_profile = str(self.config.get_profile_dir(credentials.username))
            options.add_argument(f"--user-data-dir={user_profile}")

            if credentials.headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1280,800")
            else:
                win_w, win_h = 1024, 768  # Фиксирует верстку десктопного чата
                x = max(0, SCREEN_WIDTH - win_w - 10)
                y = 10
                options.add_argument(f"--window-position={x},{y}")
                options.add_argument(f"--window-size={win_w},{win_h}")

            if credentials.user_agent:
                options.add_argument(f"user-agent={credentials.user_agent}")
            else:
                chrome_128_uas = [
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.137 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.119 Safari/537.36"
                ]
                options.add_argument(f"user-agent={random.choice(chrome_128_uas)}")
            
            if credentials.proxy:
                self._add_proxy_authentication(options, credentials.proxy)

            options.add_argument("--ignore-certificate-errors")
            
            loop = asyncio.get_event_loop()
            driver_service = Service(str(driver_path))
            
            browser = await loop.run_in_executor(None, lambda: webdriver.Chrome(service=driver_service, options=options))

            # PID chromedriver — по нему hard_close_browser добивает дерево процессов chrome
            try:
                browser._xg_pid = driver_service.process.pid
            except Exception:
                browser._xg_pid = None

            if BLOCK_MEDIA_URLS:
                # Режем тяжёлые запросы на уровне CDP: видео и аналитика. Картинки не трогаем.
                try:
                    await loop.run_in_executor(None, lambda: browser.execute_cdp_cmd("Network.enable", {}))
                    await loop.run_in_executor(None, lambda: browser.execute_cdp_cmd("Network.setBlockedURLs", {
                        "urls": [
                            "*://video.twimg.com/*", "*.mp4", "*.m3u8", "*.webm",
                            "*://ads-api.twitter.com/*", "*://ads-api.x.com/*",
                            "*://analytics.twitter.com/*", "*://*.doubleclick.net/*",
                            "*://*.google-analytics.com/*", "*://*.googletagmanager.com/*",
                        ]
                    }))
                except Exception as e:
                    print(f"CDP block URLs failed (non-fatal): {e}")

            webgl_options = [
                ("Intel Inc.", "Intel Iris OpenGL Engine"),
                ("NVIDIA Corporation", "NVIDIA GeForce GTX 1050 Ti/PCIe/SSE2"),
                ("AMD", "AMD Radeon(TM) Graphics")
            ]
            webgl_vendor, webgl_renderer = random.choice(webgl_options)
            
            stealth(
                browser, 
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor=webgl_vendor,
                renderer=webgl_renderer,
                fix_hairline=True,
                emulate_print_media=True,
                await_for_load=False
            )
            
            browser.set_page_load_timeout(45)
            browser.set_script_timeout(30)
            return browser
            
        except Exception as e:
            raise Exception(f"Failed to create browser: {str(e)}")

    def _add_proxy_authentication(self, options: Options, proxy: str) -> None:
        try:
            parts = proxy.split(":")
            if len(parts) == 4:
                host, port, username, password = parts
                manifest_json = r"""
{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Proxy Auth Extension",
    "permissions": ["proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking"],
    "background": {"scripts": ["background.js"]}
}
                """
                background_js = f"""
var config = {{
    mode: "fixed_servers",
    rules: {{
        singleProxy: {{
            scheme: "http",
            host: "{host}",
            port: parseInt({port})
        }},
        bypassList: ["localhost"]
    }}
}};
chrome.proxy.settings.set({{value: config, scope: "regular"}}, function(){{}});
function callbackFn(details) {{
    return {{ authCredentials: {{ username: "{username}", password: "{password}" }} }};
}}
chrome.webRequest.onAuthRequired.addListener(callbackFn, {{urls: ["<all_urls>"]}}, ['blocking']);
                """
                temp_dir = self.config.base_dir / "temp_proxy_extension"
                temp_dir.mkdir(parents=True, exist_ok=True)
                plugin_file = temp_dir / "proxy_auth_plugin.zip"
                with zipfile.ZipFile(plugin_file, "w") as zp:
                    zp.writestr("manifest.json", manifest_json.strip())
                    zp.writestr("background.js", background_js.strip())
                options.add_extension(str(plugin_file))
            else:
                options.add_argument(f"--proxy-server={proxy}")
        except Exception as e:
            print(f"Proxy authentication error: {e}")
