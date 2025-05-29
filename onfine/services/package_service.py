import logging
from decimal import Decimal
from functools import lru_cache
from typing import Dict, List, TypedDict

from onfine.blockchain.providers import BEP20, ERC20, TRC20
from onfine.models.wallet import Wallet

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

logger = logging.getLogger(__name__)


class PurchaseResult(TypedDict):
    """Тип для результата проверки или создания покупки."""

    purchase: Purchase
    from_database: bool


def list_packages() -> List[Package]:
    """Возвращает список всех доступных пакетов.

    Return:
        List[Package]: Список объектов пакетов.
    """
    return Package.query.all()


@lru_cache(maxsize=1)
def gas_table() -> Dict[str, Decimal]:
    """Создает таблицу газовых цен. Кэшируется для оптимизации.

    Returns:
        Dict[str, Decimal]: Словарь с газовыми ценами по сетям.
    """
    return {r.network: Decimal(r.gas_usdt) for r in NetworkGas.query.all()}


def check_balance(user: User, network: str, amount: Decimal) -> None:
    """Проверяет баланс пользователя.

    Args:
        user (User ): Пользователь, чей баланс проверяется.
        network (str): Название сети, для которой проверяется баланс.
        amount (Decimal): Сумма, которую нужно проверить.

    Raises:
        InsufficientBalanceError: Если баланс пользователя недостаточен.
    """
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
    """Проверяет наличие покупки в статусе 'pending' или создает новую.

    Args:
        user (User ): Пользователь, для которого проверяется или создается покупка.
        package_id (int): Идентификатор пакета, который пользователь хочет купить.
        network (str): Название сети, для которой производится покупка.

    Returns:
        PurchaseResult: Словарь с ключами 'purchase' и 'from_database'.

    Raises:
        PackageNotFoundError: Если пакет с указанным идентификатором не найден.
        NetworkNotFoundError: Если сеть не найдена в таблице газовых цен.
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
    """Создает новую покупку со статусом pending.

    Args:
        user (User ): Пользователь, который делает покупку.
        package_id (int): Идентификатор пакета для покупки.
        network (str): Название сети, в которой осуществляется покупка.

    Returns:
        Purchase: Созданный объект покупки.

    Raises:
        PackageNotFoundError: Если пакет с указанным идентификатором не найден.
        NetworkNotFoundError: Если сеть не найдена в таблице газовых цен.
    """
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

    purchase = Purchase(
        user=user,
        package=pkg,
        amount_usdt=pkg.price_usdt,
        gas_usdt=fee,
        network=network,
        status=PurchaseStatus.pending,
    )

    with db.session.begin():
        db.session.add(purchase)
        db.session.flush()  # Чтобы получить purchase.id
        logger.info(
            f"Создана покупка {purchase.id} для пользователя {user.id}"
        )

    return purchase


def process_purchase_confirmation(purchase_id: int) -> None:
    """Обрабатывает подтверждение покупки.

    Args:
        purchase_id (int): Идентификатор покупки для подтверждения.

    Raises:
        ValueError: Если покупка или пользователь не найдены.
    """
    p = Purchase.query.get(purchase_id)
    if not p:
        logger.error(
            f"Покупка с id {purchase_id} не найдена при подтверждении"
        )
        raise ValueError(f"Purchase with id {purchase_id} not found")

    if not p.user:
        logger.error(f"Пользователь для покупки {purchase_id} не найден")
        raise ValueError(f"User  for purchase {purchase_id} not found")

    total = p.amount_usdt + p.gas_usdt
    check_balance(p.user, p.network, total)

    try:
        with db.session.begin():
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
            db.session.flush()

            ###           # ЛОГИКА ПОДТВЕРЖДЕНИЯ ТРАНЗАКЦИИ
            success = confirm_transaction(
                transaction
            )  # НУЖНО РЕАЛИЗОВАТЬ ЭТУ ФУНКЦИЮ!!!!!
            if success:
                transaction.status = TxStatus.confirmed
                p.status = PurchaseStatus.completed
                logger.info(f"Покупка {purchase_id} подтверждена")
            else:
                transaction.status = TxStatus.failed
                p.status = PurchaseStatus.canceled
                logger.warning(
                    f"Покупка {purchase_id} отменена из-за неудачной транзакции"
                )

            db.session.commit()  # Зафиксируем изменения

            # Отправка события Kafka
            send_kafka_event(p, success)

    except Exception as e:
        logger.error(
            f"Ошибка при обработке подтверждения покупки {purchase_id}: {e}"
        )
        raise  # Можно выбросить исключение, чтобы обработать его на уровне API


def send_kafka_event(purchase: Purchase, success: bool) -> None:
    """Отправляет событие в Kafka о завершении покупки.

    Args:
        purchase (Purchase): Объект покупки, для которой отправляется событие.
        success (bool): Статус успешности завершения покупки.

    Raises:
        Exception: Если произошла ошибка при отправке события.
    """
    try:
        kfk.send(
            "purchase.completed",
            {
                "purchase_id": purchase.id,
                "user_id": purchase.user_id,
                "amount": str(purchase.amount_usdt),
                "partner_uid": getattr(purchase.user, "partner_uid", None),
                "network": purchase.network,
                "program_type": 1,
                "ts": purchase.created_at.isoformat(),
            },
        )
        logger.info(f"Отправлено событие Kafka для покупки {purchase.id}")
    except Exception as e:
        logger.error(
            f"Ошибка при отправке события Kafka для покупки {purchase.id}: {e}"
        )
        raise  # Можно выбросить исключение, чтобы обработать его на уровне API


def confirm_transaction(transaction: Transaction) -> bool:
    """Подтверждает транзакцию и возвращает статус успешности.

    Args:
        transaction (Transaction): Объект транзакции для подтверждения.

    Returns:
        bool: True, если транзакция успешно подтверждена; иначе False.
    """
    # Получаем информацию о типе сети из транзакции
    network = transaction.network
    amount = transaction.amount
    user_id = transaction.user_id  # Получаем ID пользователя из транзакции

    # Получаем кошелек пользователя
    wallet = Wallet.query.filter_by(user_id=user_id, network=network).first()
    if not wallet:
        logger.error(
            f"Кошелек для пользователя {user_id} в сети {network} не найден"
        )
        return False

    # Дешифруем приватный ключ
    try:
        user_private_key = Wallet.decrypt_pk(wallet.pk_enc)
    except Exception as e:
        logger.error(f"Ошибка при дешифровании приватного ключа: {e}")
        return False

    to_address = wallet.address  # Используем адрес из кошелька

    try:
        if network == "ERC20":
            tx_id = ERC20.transfer(user_private_key, to_address, amount)
        elif network == "BEP20":
            tx_id = BEP20.transfer(user_private_key, to_address, amount)
        elif network == "TRC20":
            tx_id = TRC20.transfer(user_private_key, to_address, amount)
        else:
            logger.error(f"Неизвестная сеть: {network}")
            return False

        logger.info(f"Транзакция {tx_id} успешно отправлена на сеть {network}")
        return True
    except InsufficientBalanceError as e:
        logger.error(f"Недостаточно средств для транзакции: {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при подтверждении транзакции: {e}")
        return False
