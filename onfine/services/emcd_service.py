import logging
import os
from typing import Any, Dict

import requests

BASE_V2 = "https://api.emcd.io/v2"
BASE_V1 = "https://api.emcd.io/v1"

logger = logging.getLogger(__name__)


class DataService:
    """
    Сервис для взаимодействия с внешним провайдером данных.

    Предоставляет методы для получения данных об аккаунте, воркерах, доходах и выплатах.
    Использует API-ключ (токен доступа), переданный в конструкторе или по умолчанию из переменной окружения BASE_API_TOKEN.
    """

    def __init__(self, access_token: str = None) -> None:
        """
        Инициализирует сервис с токеном доступа.

        Аргументы:
            access_token (str, optional): Токен для внешнего API. Если не передан, используется по умолчанию из BASE_API_TOKEN.

        Вызывает исключение:
            RuntimeError: Если ни access_token, ни переменная окружения BASE_API_TOKEN не установлены.
        """
        self.api_key = access_token or os.getenv("BASE_API_TOKEN")
        if not self.api_key:
            raise RuntimeError("Token not provided and BASE_API_TOKEN not set")

    def _get(self, url: str) -> Dict[str, Any]:
        """
        Выполняет GET-запрос к внешнему API, добавляя API-ключ к URL.

        Аргументы:
            url (str): Базовый URL для запроса (без ключа).

        Возвращает:
            dict: JSON-ответ от API.

        Вызывает исключение:
            requests.RequestException: Если запрос не удался (например, ошибка сети).
            ValueError: Если ответ пустой, не JSON или токен недействителен (401).
        """
        try:
            full_url = f"{url}/{self.api_key}"
            r = requests.get(full_url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data:
                raise ValueError("Empty response from external data service")
            return data
        except requests.HTTPError:
            if r.status_code == 401:
                raise ValueError("Invalid access token")
            raise
        except requests.RequestException as e:
            logger.error(f"Request to external data service failed: {e}")
            raise
        except ValueError as e:
            logger.error(f"Invalid JSON response from external data service: {e}")
            raise ValueError(f"Invalid JSON response: {e}")

    def get_account_info(self) -> Dict[str, Any]:
        """
        Получает информацию об аккаунте.

        Возвращает:
            dict: Данные аккаунта в формате JSON.
        """
        return self._get(f"{BASE_V2}/info")

    def get_workers(self, coin: str) -> Dict[str, Any]:
        """
        Получает информацию о воркерах для указанной coin.

        Аргументы:
            coin (str): Код coin (например, 'btc').

        Возвращает:
            dict: Данные о воркерах в формате JSON.
        """
        return self._get(f"{BASE_V1}/{coin}/workers")

    def get_income(self, coin: str) -> Dict[str, Any]:
        """
        Получает данные о доходах для указанной coin.

        Аргументы:
            coin (str): Код coin (например, 'btc').

        Возвращает:
            dict: Данные о доходах в формате JSON.
        """
        return self._get(f"{BASE_V1}/{coin}/income")

    def get_payouts(self, coin: str) -> Dict[str, Any]:
        """
        Получает данные о выплатах для указанной coin.

        Аргументы:
            coin (str): Код coin (например, 'btc').

        Возвращает:
            dict: Данные о выплатах в формате JSON.
        """
        return self._get(f"{BASE_V1}/{coin}/payouts")
