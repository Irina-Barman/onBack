import logging
from decimal import Decimal
from functools import lru_cache
from typing import Dict, List, TypedDict

from ..api.error_handlers import (
    InsufficientBalanceError,
    NetworkNotFoundError,
    PackageNotFoundError,
)
from ..extensions import db
from ..models.network_gas import NetworkGas
from ..models.package import Package
from ..models.purchase import Purchase, PurchaseStatus
from ..models.transactions import Transaction, TxStatus, TxType
from ..models.user import User
from ..services import wallet_service as wsvc
from ..utils import kafka_producer as kfk
from ..utils.ledger_decorator import LedgerType, ledger

logger = logging.getLogger(__name__)


class PurchaseResult(TypedDict):
    purchase: Purchase
    from_database: bool


def list_packages() -> List[Package]:
    """Возвращает список всех доступных пакетов."""
    return Package.query.all()


@lru_cache(maxsize=1)
def gas_table() -> Dict[str, Decimal]:
    """Создает таблицу газовых цен. Кэшируется для оптимизации."""
    return {r.network: Decimal(r.gas_usdt) for r in NetworkGas.query.all()}


def check_balance(user: User, network: str, amount: Decimal) -> None:
    """Проверяет баланс пользователя."""
    balance = wsvc.balance_for(user, network)
    if balance < amount:
        logger.warning(
            f"Недостаточно средств у пользователя {user.id} на сети {network}: "
            f"требуется {amount}, доступно {balance}"
        )
        raise InsufficientBalanceError("Insufficient balance for the purchase")


def check_or_create_purchase(
    user: User, package_id: int, network: str
) -> PurchaseResult:
    """
    Проверяет наличие покупки в статусе 'pending' или создает новую.
    Возвращает словарь с ключами 'purchase' и 'from_database'.
    """
    pending_purchase = Purchase.query.filter_by(
        user_id=user.id, status=PurchaseStatus.pending, network=network
    ).first()

    if pending_purchase:
        logger.info(
            f"Найдена ожидающая покупка {pending_purchase.id} для пользователя {user.id} в сети {network}"
        )
        return {"purchase": pending_purchase, "from_database": True}

    pkg = Package.query.get(package_id)
    if not pkg:
        logger.error(f"Пакет с id {package_id} не найден")
        raise PackageNotFoundError(f"Package with id {package_id} not found")

    fee = gas_table().get(network)
    if fee is None:
        logger.error(f"Сеть {network} не найдена в таблице газовых цен")
        raise NetworkNotFoundError(f"Network {network} not found")

    total = pkg.price_usdt + fee
    check_balance(user, network, total)

    new_purchase = create_purchase(user, package_id, network)
    return {"purchase": new_purchase, "from_database": False}


def create_purchase(user: User, package_id: int, network: str) -> Purchase:
    """Создает новую покупку и списывает средства."""
    pkg = Package.query.get(package_id)
    if not pkg:
        logger.error(f"Пакет с id {package_id} не найден при создании покупки")
        raise PackageNotFoundError(f"Package with id {package_id} not found")

    fee = gas_table().get(network)
    if fee is None:
        logger.error(
            f"Сеть {network} не найдена в таблице газовых цен при создании покупки"
        )
        raise NetworkNotFoundError(f"Network {network} not found")

    total = pkg.price_usdt + fee

    # Проверка баланса перед списанием
    check_balance(user, network, total)

    # Обеспечиваем атомарность операции создания покупки и списания средств
    with db.session.begin():
        logger.info(
            f"Списываем средства у пользователя {user.id} на сумму {total}"
        )
        wsvc.debit(user, network, total)

        purchase = Purchase(
            user=user,
            package=pkg,
            amount_usdt=pkg.price_usdt,
            gas_usdt=fee,
            network=network,
            status=PurchaseStatus.pending,
        )
        db.session.add(purchase)
        db.session.flush()  # Чтобы получить purchase.id

        transaction = Transaction(
            user_id=user.id,
            type=TxType.purchase,
            status=TxStatus.pending,
            network=network,
            amount=pkg.price_usdt,
            fee=fee,
            purchase_id=purchase.id,
        )
        db.session.add(transaction)
        logger.info(
            f"Создана покупка {purchase.id} для пользователя {user.id}"
        )

    return purchase


def confirm_purchase(purchase_id: int, success: bool) -> Purchase:
    """Подтверждает покупку и отправляет событие в Kafka."""
    p = Purchase.query.get(purchase_id)
    if not p:
        logger.error(
            f"Покупка с id {purchase_id} не найдена при подтверждении"
        )
        raise ValueError(f"Purchase with id {purchase_id} not found")

    new_status = (
        PurchaseStatus.completed if success else PurchaseStatus.canceled
    )

    with db.session.begin():
        # Обновляем статус покупки
        p.status = new_status

        # Создаем транзакцию
        transaction = Transaction(
            user_id=p.user_id,
            type=TxType.purchase,
            status=TxStatus.pending,
            network=p.network,
            amount=p.amount_usdt,
            fee=p.gas_usdt,
            purchase_id=p.id,
        )
        db.session.add(transaction)
        db.session.flush()  # Получаем id транзакции

        # Если покупка подтверждена, обновляем статус транзакции и отправляем событие
        if success:
            transaction.status = TxStatus.confirmed
            try:
                kfk.send(
                    "purchase.completed",
                    {
                        "purchase_id": p.id,
                        "user_id": p.user_id,
                        "amount": str(p.amount_usdt),
                        "partner_uid": p.user.partner_uid,
                        "network": p.network,
                        "program_type": 1,
                        "ts": p.created_at.isoformat(),
                    },
                )
                logger.info(
                    f"Отправлено событие Kafka для покупки {purchase_id}"
                )
            except Exception as e:
                logger.error(
                    f"Ошибка при отправке события Kafka для покупки {purchase_id}: {e}"
                )
                raise  # Можно выбросить исключение, чтобы обработать его на уровне API

        logger.info(f"Статус покупки {purchase_id} обновлен на {p.status}")

    return p
