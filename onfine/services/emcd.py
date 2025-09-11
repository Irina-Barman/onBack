import os
from datetime import datetime, timezone
from typing import Any, Dict

import requests

from onfine.models.emcd_account import EMCDAccountInfo, EMCDCoinInfo
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
    Для общего пула pool_id=0, без user_id.
    """

    def __init__(self) -> None:
        self.emcd_service = EMCDService()
        self.pool_id = 0  # фиксированный для общего пула

    def save_account_info(self, account_data: dict) -> None:
        """
        Сохраняет EMCDAccountInfo и EMCDCoinInfo из данных /info.
        """
        username = account_data.get('username', 'unknown')
        date = datetime.now(tz=timezone.utc).date()

        # Поиск или создание записи аккаунта
        account_info = EMCDAccountInfo.query.filter_by(
            pool_id=self.pool_id, date=date).first()
        if not account_info:
            account_info = EMCDAccountInfo(
                pool_id=self.pool_id,
                username=username,
                date=date
            )
            db.session.add(account_info)
            db.session.flush()  # чтобы получить account_info.id

        # Сохраняем данные по каждой монете
        for coin_id, coin_data in account_data.get('coins', {}).items():
            coin_info = EMCDCoinInfo.query.filter_by(
                account_info_id=account_info.id,
                coin_id=coin_id,
                date=date
            ).first()

            if coin_info:
                # Обновляем существующую запись
                coin_info.address = coin_data.get('address', '')
                coin_info.balance = float(coin_data.get('balance', 0))
                coin_info.total_paid = float(coin_data.get('total_paid', 0))
                coin_info.total_reward = float(coin_data.get('total_reward', 0))
                coin_info.min_payout = float(coin_data.get('min_payout', 0))
            else:
                # Создаем новую запись
                coin_info = EMCDCoinInfo(
                    account_info_id=account_info.id,
                    coin_id=coin_id,
                    date=date,
                    address=coin_data.get('address', ''),
                    balance=float(coin_data.get('balance', 0)),
                    total_paid=float(coin_data.get('total_paid', 0)),
                    total_reward=float(coin_data.get('total_reward', 0)),
                    min_payout=float(coin_data.get('min_payout', 0)),
                    token_id=None
                )
                db.session.add(coin_info)

        db.session.commit()

    def save_income(self, coin: str) -> None:
        """
        Сохраняет доходы для монеты в EMCDIncome без user_id, с pool_id=0.
        """
        data = self.emcd_service.get_income(coin)
        if 'data' not in data:
            return

        for item in data['data']:
            date = datetime.fromtimestamp(
                item['timestamp'], tz=timezone.utc).date()

            # Проверяем существование записи по дате, монете и pool_id=0
            existing = EMCDIncome.query.filter_by(
                user_id=None,  # user_id нет, можно убрать из фильтра или сделать nullable
                coin=coin,
                date=date
            ).first()
            if existing:
                continue

            income = EMCDIncome(
                user_id=None,  # в модели user_id nullable? Если нет, надо изменить модель
                coin=coin,
                token_id=None,
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

    def save_payouts(self, coin: str) -> None:
        """
        Сохраняет выплаты для монеты в EMCDPayout без user_id, с pool_id=0.
        """
        data = self.emcd_service.get_payouts(coin)
        if 'data' not in data:
            return

        for item in data['data']:
            date = datetime.fromtimestamp(
                item['timestamp'], tz=timezone.utc).date()

            existing = EMCDPayout.query.filter_by(
                user_id=None,
                coin=coin,
                date=date
            ).first()
            if existing:
                continue

            payout = EMCDPayout(
                user_id=None,
                coin=coin,
                token_id=None,
                code=item.get('code', 0),
                timestamp=item['timestamp'],
                gmt_time=item['gmt_time'],
                payout=item.get('amount', 0),  # В API поле называется amount
                type_='payout',  # В API поле type отсутствует, можно задать вручную
                tx_id=item.get('txid'),
                date=date
            )
            db.session.add(payout)
        db.session.commit()

    def save_all(self) -> None:
        """
        Сохраняет всю информацию: account info, доходы и выплаты по всем монетам.
        """
        account_data = self.emcd_service.get_account_info()
        self.save_account_info(account_data)

        for coin_id in account_data.get('coins', {}).keys():
            self.save_income(coin_id)
            self.save_payouts(coin_id)