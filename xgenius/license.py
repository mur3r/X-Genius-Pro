"""
Проверка лицензионного ключа по Google-таблице.
"""

import csv
from datetime import datetime
from io import StringIO

import requests

from xgenius.settings import LICENSE_SHEET_URL


# --------------------- Функция проверки лицензии ---------------------
def verify_license(user_key: str):
    sheet_url = LICENSE_SHEET_URL
    csv_url = sheet_url.replace("/edit?usp=sharing", "/export?format=csv")
    
    try:
        with requests.Session() as session:
            response = session.get(csv_url, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            csv_file = StringIO(response.text)
            reader = csv.reader(csv_file)
            
            for row in reader:
                if not row: continue
                key_in_sheet, expiration_date_str = row[0], row[1]
                if key_in_sheet == user_key:
                    try:
                        expiration_date = datetime.strptime(expiration_date_str, "%d.%m.%Y %H:%M:%S")
                        if expiration_date >= datetime.now():
                            return (True, f"Key successfully activated. Access until: {expiration_date_str}", expiration_date)
                        else:
                            return (False, f"Your license key expired on {expiration_date_str}.", None)
                    except ValueError:
                        return (False, "Date format error in the license sheet. Please contact support.", None)
            return (False, "Invalid license key.", None)
            
    except requests.exceptions.RequestException:
        return (False, "Failed to connect to the license server. Please check your internet connection.", None)
    except Exception as e:
        return (False, f"An unknown error occurred: {e}", None)
