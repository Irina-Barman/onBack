import os
from datetime import datetime, timezone
from typing import Any, Dict

import requests

from onfine.models.emcd_income import EMCDIncome
from onfine.models.emcd_payouts import EMCDPayout

from ..extensions import db

BASE_V2 = "https://api.emcd.io/v2"
BASE_V1 = "https://api.emcd.io/v1"


class EMCDService:
    """
    Сервис для взаимодействия с EMCD API.

    Предоставляет методы для получения данных о аккаунте, воркерах, доходах и выплатах.
    Использует API-ключ из переменной окружения EMCD_API_KEY для аутентификации.
    """

    def __init__(self) -> None:
        """
        Инициализирует сервис с API-ключом.

        Raises:
            RuntimeError: Если переменная окружения EMCD_API_KEY не установлена.
        """
        self.api_key = os.getenv("EMCD_API_KEY")
        if not self.api_key:
            raise RuntimeError("EMCD_API_KEY is not set")

    def _get(self, url: str) -> Dict[str, Any]:
        """
        Выполняет GET-запрос к EMCD API с добавлением API-ключа в URL.

        Args:
            url (str): Базовый URL для запроса (без ключа).

        Returns:
            dict: JSON-ответ от API.

        Raises:
            requests.RequestException: Если запрос не удался (например, ошибка сети или аутентификации).
        """
        r = requests.get(f"{url}/{self.api_key}", timeout=10)
        r.raise_for_status()
        return r.json()

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


class EMCDDataSaver:
    """
    Класс для сохранения данных из EMCD API в базу данных.

    Используется для сохранения доходов и выплат для конкретного пользователя.
    Предотвращает дублирование записей на основе даты, монеты и user_id.
    """

    def __init__(self, user_id: int) -> None:
        """
        Инициализирует савер с ID пользователя.

        Args:
            user_id (int): ID пользователя для сохранения данных.
        """
        self.user_id = user_id
        self.emcd_service = EMCDService()

    def save_income(self, coin: str, income_data: Dict[str, Any]) -> None:
        """
        Сохраняет данные о доходах для указанной монеты.

        Args:
            coin (str): Код монеты (например, 'btc').

        Note:
            Пропускает существующие записи по дате, монете и user_id.
        """
        data = self.emcd_service.get_income(coin)
        if 'data' not in data:
            return

        for item in data['data']:
            date = datetime.fromtimestamp(
                item['timestamp'], tz=timezone.utc).date()
            existing = EMCDIncome.query.filter_by(
                user_id=self.user_id, date=date, coin=coin
            ).first()
            if existing:
                continue

            income = EMCDIncome(
                user_id=self.user_id,
                coin=coin,
                token_id=None,  # Normalize via token_id if needed
                code=item.get('code', 0),
                timestamp=item['timestamp'],
                gmt_time=item['gmt_time'],
                income=item['income'],
                type_=item['type'],
                total_hashrate=item.get('total_hashrate', 0),
                date=date
            )
            db.session.add(income)
        db.session.commit()

    def save_payouts(self, coin: str, payouts_data: Dict[str, Any]) -> None:
        """
        Сохраняет данные о выплатах для указанной монеты.

        Args:
            coin (str): Код монеты (например, 'btc').

        Note:
            Пропускает существующие записи по дате, монете и user_id.
        """
        data = self.emcd_service.get_payouts(coin)
        if 'data' not in data:
            return

        for item in data['data']:
            date = datetime.fromtimestamp(
                item['timestamp'], tz=timezone.utc).date()
            existing = EMCDPayout.query.filter_by(
                user_id=self.user_id, date=date, coin=coin
            ).first()
            if existing:
                continue

            payout = EMCDPayout(
                user_id=self.user_id,
                coin=coin,
                token_id=None,  # Normalize via token_id if needed
                code=item.get('code', 0),
                timestamp=item['timestamp'],
                gmt_time=item['gmt_time'],
                payout=item['payout'],
                type_=item['type'],
                tx_id=item.get('tx_id'),
                date=date
            )
            db.session.add(payout)
        db.session.commit()

    def save_all_for_coin(self, coin: str) -> None:
        """
        Сохраняет все данные (доходы и выплаты) для указанной монеты.

        Args:
            coin (str): Код монеты (например, 'btc').
        """
        self.save_income(coin)
        self.save_payouts(coin)
