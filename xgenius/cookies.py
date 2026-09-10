"""
Куки аккаунта (файл kook/@user/cookies.json + БД) и лог-файл logstest.
"""

import json
from pathlib import Path

from selenium import webdriver


def log_account_to_file(username: str, password: str, proxy: str, auth_token: str, ct0_token: str, groups_count: int, followers_count: int):
    """
    Записывает данные аккаунта в файл logstest в формате:
    логин:пасс:прокси:аутх_токен:цто:колво_чатов:колво_подписчиков
    """
    try:
        import os
        log_file = os.path.join(os.getcwd(), 'logstest')
        log_line = f"{username}:{password}:{proxy}:{auth_token}:{ct0_token}:{groups_count}:{followers_count}\n"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)
        print(f"[LOGSTEST] Записаны данные аккаунта {username} в файл {log_file}")
    except Exception as e:
        print(f"[LOGSTEST] Ошибка записи в файл: {e}")

def get_cookies_file_path(config: 'Config', username: str) -> Path:
    kook_folder = config.base_dir / "kook"
    kook_folder.mkdir(parents=True, exist_ok=True)
    account_folder = kook_folder / f"@{username}"
    account_folder.mkdir(parents=True, exist_ok=True)
    return account_folder / "cookies.json"

def save_cookies(browser: webdriver.Chrome, config: 'Config', username: str, db_manager=None, pc_id=None) -> None:
    cookies = browser.get_cookies()
    cookie_dict = {}
    for cookie in cookies:
        domain = cookie.get("domain")
        if domain not in cookie_dict:
            cookie_dict[domain] = []
        cookie_dict[domain].append(cookie)
    file_path = get_cookies_file_path(config, username)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(cookie_dict, f, indent=4)
    print(f"Cookies saved to {file_path}")
    if db_manager and pc_id:
        db_manager.update_cookies(pc_id, username, cookie_dict)

def load_cookies(browser: webdriver.Chrome, config: 'Config', username: str, db_manager=None, pc_id=None) -> None:
    file_path = get_cookies_file_path(config, username)
    cookie_data = None
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            cookie_data = json.load(f)
        print(f"Cookies loaded from {file_path}")
    elif db_manager and pc_id:
        cookie_data = db_manager.get_cookies(pc_id, username)
        if cookie_data:
            print(f"Cookies loaded from DB for {username}")
        else:
            print("No cookies file or DB entry found.")
            return
    else:
        print("No cookies file found.")
        return

    # Раньше код ходил на https://{domain} для каждого домена из файла, т.е. на
    # "https://.x.com" — это невалидный адрес, Chrome показывал страницу ошибки и
    # add_cookie падал для ВСЕХ кук x.com. Куки нужно добавлять, находясь на x.com.
    browser.get("https://x.com")

    if isinstance(cookie_data, list):
        all_cookies = list(cookie_data)
    else:
        all_cookies = [c for batch in cookie_data.values() for c in (batch or [])]

    added = 0
    for cookie in all_cookies:
        domain = (cookie.get("domain") or "").lower()
        if "x.com" not in domain:
            continue  # twitter.com и прочее X больше не использует
        clean = {k: v for k, v in cookie.items() if k in ("name", "value", "domain", "path", "secure", "httpOnly", "expiry", "sameSite")}
        try:
            browser.add_cookie(clean)
            added += 1
        except Exception as e:
            print(f"Failed to add cookie {clean.get('name')}: {e}")
    print(f"Cookies applied: {added}/{len(all_cookies)}")
