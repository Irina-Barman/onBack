"""
Модуль сервиса для взаимодействия с API EMCD.

Класс EMCDService предоставляет методы для получения данных о пользователе и статистике по майнингу через API EMCD.

Зависимости:
- os: для получения переменной окружения EMCD_API_KEY.
- requests: для выполнения HTTP-запросов к API EMCD.

Константы:
- BASE_V2 (str): базовый URL для версии 2 API EMCD.
- BASE_V1 (str): базовый URL для версии 1 API EMCD.

Класс EMCDService:
- __init__()
    Инициализирует сервис, загружая API-ключ из переменных окружения.
    Выбрасывает RuntimeError, если ключ не установлен.

- _get(url: str) -> dict
    Вспомогательный приватный метод для выполнения GET-запроса к API с таймаутом 10 секунд.
    Возвращает распарсенный JSON-ответ.
    Выбрасывает исключения requests при ошибках HTTP.

- get_account_info() -> dict
    Получает общую информацию о пользователе (endpoint v2/info).

- get_workers(coin: str) -> dict
    Получает данные о подключённых воркерах для указанной криптовалюты (endpoint v1/{coin}/workers).

- get_income(coin: str) -> dict
    Получает информацию о доходах по указанной криптовалюте (endpoint v1/{coin}/income).

- get_payouts(coin: str) -> dict
    Получает данные о выплатах по указанной криптовалюте (endpoint v1/{coin}/payouts).
"""


import os

import requests

BASE_V2 = "https://api.emcd.io/v2"
BASE_V1 = "https://api.emcd.io/v1"


class EMCDService:
    def __init__(self) -> None:
        self.api_key = os.getenv("EMCD_API_KEY")
        if not self.api_key:
            raise RuntimeError("EMCD_API_KEY is not set")

    def _get(self, url: str) -> dict:
        r = requests.get(f"{url}/{self.api_key}", timeout=10)
        r.raise_for_status()
        return r.json()

    def get_account_info(self) -> dict:
        """General user data: v2/info"""
        return self._get(f"{BASE_V2}/info")

    def get_workers(self, coin: str) -> dict:
        """Connected workers: v1/{coin}/workers"""
        return self._get(f"{BASE_V1}/{coin}/workers")

    def get_income(self, coin: str) -> dict:
        """Rewards on account: v1/{coin}/income"""
        return self._get(f"{BASE_V1}/{coin}/income")

    def get_payouts(self, coin: str) -> dict:
        """Payouts: v1/{coin}/payouts"""
        return self._get(f"{BASE_V1}/{coin}/payouts")
