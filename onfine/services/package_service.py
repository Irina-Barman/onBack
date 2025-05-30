import logging
import time
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
    """Тип для результата проверки или создания покупки.

    Attributes:
        purchase (Purchase): Объект покупки.
        from_database (bool): Флаг, указывающий, была ли покупка взята из базы данных (True)
            или создана новая (False).
    """

    purchase: Purchase
    from_database: bool


def list_packages() -> List[Package]:
    """Возвращает список всех доступных пакетов.

    Получает все пакеты из базы данных.

    Returns:
        List[Package]: Список объектов Package.
    """
    return Package.query.all()


@lru_cache(maxsize=1)
def gas_table() -> Dict[str, Decimal]:
    """Создает и кэширует таблицу газовых цен для всех сетей.

    Извлекает из базы данных все записи с ценами газа по сетям и формирует словарь.

    Returns:
        Dict[str, Decimal]: Словарь, где ключ — название сети, значение — цена газа в USDT.
    """
    return {r.network: Decimal(r.gas_usdt) for r in NetworkGas.query.all()}


def reset_gas_table_cache() -> None:
    """Сбрасывает кэш таблицы газовых цен.

    Очищает кэш функции gas_table, чтобы обновить данные из базы.
    """
    gas_table.cache_clear()
    logger.info("Кэш таблицы газовых цен сброшен.")


def check_balance(user: User, network: str, amount: Decimal) -> None:
    """Проверяет, что у пользователя достаточно средств на указанной сети.

    Args:
        user (User): Пользователь, чей баланс проверяется.
        network (str): Название сети (например, 'ERC20', 'BEP20').
        amount (Decimal): Необходимая сумма для проверки.

    Exceptions:
        InsufficientBalanceError: Если баланс пользователя меньше требуемой суммы.
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
    """Проверяет наличие ожидающей покупки или создает новую.

    Проверяет, есть ли у пользователя в указанной сети покупка со статусом 'pending'.
    Если есть — возвращает её, иначе создает новую покупку с учетом цены пакета и газа.

    Args:
        user (User): Пользователь, совершающий покупку.
        package_id (int): ID пакета, который хочет купить пользователь.
        network (str): Название сети, в которой совершается покупка.

    Exceptions:
        PackageNotFoundError: Если пакет с указанным ID не найден.
        NetworkNotFoundError: Если сеть отсутствует в таблице газовых цен.
        InsufficientBalanceError: Если у пользователя недостаточно средств.

    Returns:
        PurchaseResult: Словарь с объектом покупки и флагом источника данных.
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

    new_purchase = create_purchase(user, pkg, network)
    return {"purchase": new_purchase, "from_database": False}


def create_purchase(user: User, pkg: Package, network: str) -> Purchase:
    """Создает новую покупку с статусом 'pending' и сохраняет в базе.

    Args:
        user (User): Пользователь, совершающий покупку.
        pkg (Package): Пакет, который покупается.
        network (str): Сеть, в которой совершается покупка.

    Exceptions:
        NetworkNotFoundError: Если сеть отсутствует в таблице газовых цен.

    Returns:
        Purchase: Созданный объект покупки.
    """
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
    """Обрабатывает подтверждение покупки: создает транзакцию, подтверждает её и обновляет статусы.

    Args:
        purchase_id (int): ID покупки, которую нужно подтвердить.

    Exceptions:
        ValueError: Если покупка или пользователь не найдены.
        Exception: При ошибках в процессе обработки.
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

            # Логика подтверждения транзакции
            success = confirm_transaction(transaction)
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
        purchase (Purchase): Объект покупки.
        success (bool): Флаг успешности покупки.
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
                "success": success,
            },
        )
        logger.info(f"Отправлено событие Kafka для покупки {purchase.id}")
    except Exception as e:
        logger.error(
            f"Ошибка при отправке события Kafka для покупки {purchase.id}: {e}"
        )
        raise  # Можно выбросить исключение, чтобы обработать его на уровне API


def check_transaction_status(network: str, tx_id: str) -> bool:
    """Проверяет статус транзакции в указанной сети по идентификатору.

    Args:
        network (str): Название сети (ERC20, BEP20, TRC20).
        tx_id (str): Идентификатор транзакции.

    Returns:
        bool: True, если транзакция подтверждена (статус 1), иначе False.
    """
    try:
        if network == "ERC20":
            receipt = ERC20.get_transaction_receipt(tx_id)
        elif network == "BEP20":
            receipt = BEP20.get_transaction_receipt(tx_id)
        elif network == "TRC20":
            receipt = TRC20.get_transaction_receipt(tx_id)
        else:
            logger.error(f"Неизвестная сеть для проверки: {network}")
            return False

        if receipt is None:
            # Транзакция ещё не обработана сетью, статус неизвестен
            return False
        # В блокчейн-сетях статус 1 обычно означает успешное выполнение транзакции
        return receipt.status == 1
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса транзакции {tx_id}: {e}")
        return False


def confirm_transaction(transaction: Transaction) -> bool:
    """
    Подтверждает транзакцию: выполняет перевод средств и проверяет подтверждение.

    Получает приватный ключ пользователя, инициирует перевод средств на адрес кошелька,
    затем проверяет статус транзакции с повторными попытками.

    Args:
        transaction (Transaction): Объект транзакции для подтверждения.

    Returns:
        bool: True, если транзакция подтверждена, False в случае ошибки или неудачи.
    """
    network = transaction.network
    amount = transaction.amount
    user_id = transaction.user_id  # Получаем ID пользователя из транзакции

    # Получаем кошелек пользователя для указанной сети
    wallet = Wallet.query.filter_by(user_id=user_id, network=network).first()
    if not wallet:
        logger.error(
            f"Кошелек для пользователя {user_id} в сети {network} не найден"
        )
        return False

    # Дешифруем приватный ключ кошелька
    try:
        user_private_key = Wallet.decrypt_pk(wallet.pk_enc)
    except Exception as e:
        logger.error(f"Ошибка при дешифровании приватного ключа: {e}")
        return False

    to_address = wallet.address  # Адрес для перевода средств
    logger.info(f"Отправка средств на адрес {to_address}")

    try:
        # Выполнение перевода в зависимости от сети
        if network == "ERC20":
            tx_id = ERC20.transfer(user_private_key, to_address, amount)
        elif network == "BEP20":
            tx_id = BEP20.transfer(user_private_key, to_address, amount)
        elif network == "TRC20":
            tx_id = TRC20.transfer(user_private_key, to_address, amount)
        else:
            logger.error(f"Неизвестная сеть: {network}")
            return False

        # Проверка статуса транзакции с несколькими попытками (до 5 попыток по 10 секунд)
        max_retries = 5
        delay_seconds = 10
        for attempt in range(max_retries):
            time.sleep(delay_seconds)
            if check_transaction_status(network, tx_id):
                logger.info(f"Транзакция {tx_id} подтверждена")
                return True
            else:
                logger.info(
                    f"Ожидание подтверждения транзакции {tx_id} (попытка {attempt + 1})"
                )

        logger.warning(f"Транзакция {tx_id} не подтверждена после ожидания")
        return False

    except InsufficientBalanceError as e:
        logger.error(f"Недостаточно средств для транзакции: {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при подтверждении транзакции: {e}")
        return False
