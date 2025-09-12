import logging
from datetime import datetime, timezone
from typing import Any, Dict

from onfine.models.emcd_account import EMCDAccountInfo, EMCDCoinInfo
from onfine.models.emcd_income import EMCDIncome
from onfine.models.emcd_payouts import EMCDPayout
from onfine.services.emcd_service import EMCDService

from ..extensions import db

BASE_V2 = "https://api.emcd.io/v2"
BASE_V1 = "https://api.emcd.io/v1"

logger = logging.getLogger(__name__)


class EMCDDataSaver:
    """
    Класс для сохранения данных из EMCD API в базу данных.
    Для общего пула pool_id=0, без user_id.
    """

    def __init__(self) -> None:
        self.emcd_service = EMCDService()
        self.pool_id = 0  # фиксированный для общего пула

    def _validate_income_data(self, data: Dict[str, Any]) -> None:
        """Валидация данных income на основе схемы."""
        if "income" not in data or not isinstance(data["income"], list):
            raise ValueError(
                "Invalid income data: missing or invalid 'income' list")
        for item in data["income"]:
            required_fields = ["code", "timestamp",
                               "gmt_time", "income", "type", "total_hashrate"]
            for field in required_fields:
                if field not in item:
                    raise ValueError(f"Missing field '{field}' in income item")
            if not isinstance(item["income"], (int, float)):
                raise ValueError(
                    f"Invalid 'income' type: {type(item['income'])}")
            if not isinstance(item["timestamp"], int):
                raise ValueError(
                    f"Invalid 'timestamp' type: {type(item['timestamp'])}")

    def _validate_payouts_data(self, data: Dict[str, Any]) -> None:
        """Валидация данных payouts на основе схемы."""
        if "payouts" not in data or not isinstance(data["payouts"], list):
            raise ValueError(
                "Invalid payouts data: missing or invalid 'payouts' list")
        for item in data["payouts"]:
            required_fields = ["timestamp", "gmt_time", "amount", "txid"]
            for field in required_fields:
                if field not in item:
                    raise ValueError(
                        f"Missing field '{field}' in payouts item")
            if not isinstance(item["amount"], (int, float)):
                raise ValueError(
                    f"Invalid 'amount' type: {type(item['amount'])}")
            if not isinstance(item["timestamp"], int):
                raise ValueError(
                    f"Invalid 'timestamp' type: {type(item['timestamp'])}")

    def save_account_info(self, account_data: dict) -> None:
        """
        Сохраняет EMCDAccountInfo и EMCDCoinInfo из данных /info.
        """
        username = account_data.get('username', 'unknown')
        date = datetime.now(tz=timezone.utc).date()

        try:
            with db.session.begin():
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
                        coin_info.total_paid = float(
                            coin_data.get('total_paid', 0))
                        coin_info.total_reward = float(
                            coin_data.get('total_reward', 0))
                        coin_info.min_payout = float(
                            coin_data.get('min_payout', 0))
                    else:
                        # Создаем новую запись
                        coin_info = EMCDCoinInfo(
                            account_info_id=account_info.id,
                            coin_id=coin_id,
                            date=date,
                            address=coin_data.get('address', ''),
                            balance=float(coin_data.get('balance', 0)),
                            total_paid=float(coin_data.get('total_paid', 0)),
                            total_reward=float(
                                coin_data.get('total_reward', 0)),
                            min_payout=float(coin_data.get('min_payout', 0)),
                            token_id=None
                        )
                        db.session.add(coin_info)
        except Exception as e:
            logger.error(f"Error saving account info: {e}")
            raise

    def save_income(self, coin: str) -> None:
        """
        Сохраняет доходы для монеты в EMCDIncome без user_id, с pool_id=0.
        """
        data = self.emcd_service.get_income(coin)
        self._validate_income_data(data)  # Валидация

        try:
            with db.session.begin():
                for item in data['income']:
                    date = datetime.fromtimestamp(
                        item['timestamp'], tz=timezone.utc).date()

                    # Проверяем существование записи по дате, монете и pool_id=0
                    existing = EMCDIncome.query.filter_by(
                        user_id=None,  # Если user_id не nullable, добавьте дефолт или измените модель
                        coin=coin,
                        date=date
                    ).first()
                    if existing:
                        continue

                    income = EMCDIncome(
                        user_id=None,
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
        except Exception as e:
            logger.error(f"Error saving income for {coin}: {e}")
            raise

    def save_payouts(self, coin: str) -> None:
        """
        Сохраняет выплаты для монеты в EMCDPayout без user_id, с pool_id=0.
        """
        data = self.emcd_service.get_payouts(coin)
        self._validate_payouts_data(data)  # Валидация

        try:
            with db.session.begin():
                for item in data['payouts']:
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
                        # В API поле называется amount
                        payout=item.get('amount', 0),
                        type_='payout',  # В API поле type отсутствует, можно задать вручную
                        tx_id=item.get('txid'),
                        date=date
                    )
                    db.session.add(payout)
        except Exception as e:
            logger.error(f"Error saving payouts for {coin}: {e}")
            raise

    def save_all(self) -> None:
        """
        Сохраняет всю информацию: account info, доходы и выплаты по всем монетам.
        """
        try:
            account_data = self.emcd_service.get_account_info()
            self.save_account_info(account_data)

            for coin_id in account_data.get('coins', {}).keys():
                self.save_income(coin_id)
                self.save_payouts(coin_id)
        except Exception as e:
            logger.error(f"Error in save_all: {e}")
            raise
