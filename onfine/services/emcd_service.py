import logging
import os
from typing import Any, Dict

import requests

BASE_V2 = "https://api.emcd.io/v2"
BASE_V1 = "https://api.emcd.io/v1"

logger = logging.getLogger(__name__)


class EMCDService:
    """
    Сервис для взаимодействия с EMCD API.

    Предоставляет методы для получения данных о аккаунте, воркерах, доходах и выплатах.
    Использует API-ключ (EMCD-токен), переданный в конструктор или базовый из переменной окружения EMCD_API_KEY.
    """

    BASE_V2 = "https://api.emcd.io/v2"
    BASE_V1 = "https://api.emcd.io/v1"

    def __init__(self, emcd_token: str = None) -> None:
        """
        Инициализирует сервис с EMCD-токеном.

        Args:
            emcd_token (str, optional): Токен для EMCD API. Если не передан, используется базовый из EMCD_API_KEY.

        Raises:
            RuntimeError: Если ни emcd_token, ни переменная окружения EMCD_API_KEY не установлены.
        """
        self.api_key = emcd_token or os.getenv("EMCD_API_KEY")
        if not self.api_key:
            raise RuntimeError("EMCD token is not provided and EMCD_API_KEY is not set")

    def _get(self, url: str) -> Dict[str, Any]:
        """
        Выполняет GET-запрос к EMCD API с добавлением API-ключа в URL.

        Args:
            url (str): Базовый URL для запроса (без ключа).

        Returns:
            dict: JSON-ответ от API.

        Raises:
            requests.RequestException: Если запрос не удался (например, ошибка сети).
            ValueError: Если ответ пустой, не JSON или токен невалидный (401).
        """
        try:
            r = requests.get(f"{url}/{self.api_key}", timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data:
                raise ValueError("Empty response from EMCD API")
            return data
        except requests.HTTPError as e:
            if r.status_code == 401:
                raise ValueError("Invalid EMCD token") from e
            raise  # Передаем другие HTTP-ошибки выше
        except requests.RequestException:
            raise  # Передаем исключение выше
        except ValueError as e:
            raise ValueError(f"Invalid JSON response: {e}")

    def get_account_info(self) -> Dict[str, Any]:
        """
        Получает информацию об аккаунте.

        Returns:
            dict: Данные об аккаунте в формате JSON.
        """
        return self._get(f"{BASE_V2}/info")

    def get_workers(self, coin: str) -> Dict[str, Any]:
        """
        Получает информацию о воркерах для указанной монеты.

        Args:
            coin (str): Код монеты (например, 'btc').

        Returns:
            dict: Данные о воркерах в формате JSON.
        """
        return self._get(f"{BASE_V1}/{coin}/workers")

    def get_income(self, coin: str) -> Dict[str, Any]:
        """
        Получает данные о доходах для указанной монеты.

        Args:
            coin (str): Код монеты (например, 'btc').

        Returns:
            dict: Данные о доходах в формате JSON.
        """
        return self._get(f"{BASE_V1}/{coin}/income")

    def get_payouts(self, coin: str) -> Dict[str, Any]:
        """
        Получает данные о выплатах для указанной монеты.

        Args:
            coin (str): Код монеты (например, 'btc').

        Returns:
            dict: Данные о выплатах в формате JSON.
        """
        return self._get(f"{BASE_V1}/{coin}/payouts")
