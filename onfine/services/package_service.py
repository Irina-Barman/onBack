import logging
import time
from decimal import Decimal
from functools import lru_cache
from typing import Any, Dict, List, TypedDict

from sqlalchemy.orm import joinedload
from web3 import Web3

from onfine.blockchain.providers import TRC20, ProviderManager
from onfine.models.wallet import Wallet
from onfine.services.email_service import EmailService

from ..api.error_handlers import (
    InsufficientBalanceError,
    NetworkNotFoundError,
    PackageNotFoundError,
)
from ..extensions import db
from ..models.network_gas import NetworkGas
from ..models.package import Package
from ..models.purchase import Purchase, PurchaseStatus
from ..models.transactions import Transaction
from ..models.user import User
from ..utils import kafka_producer as kfk

logger = logging.getLogger(__name__)


class PurchaseResult(TypedDict):
    """
    Тип для результата проверки или создания покупки.

    Attributes:
        purchase (Purchase): Объект покупки.
        from_database (bool): Флаг, указывающий, была ли покупка взята из базы данных (True)
            или создана новая (False).
    """

    purchase: Purchase
    from_database: bool


def list_packages() -> List[Dict[str, Any]]:
    """
    Получает список всех пакетов с их основными атрибутами и свойствами.

    Использует жадную загрузку (joinedload) для оптимизации запросов к связанным таблицам.

    Returns:
        List[Dict[str, Any]]: Список словарей с данными по каждому пакету,
        включая свойства из PackageProperty.
    """
    packages: List[Package] = Package.query.options(
        joinedload(Package.package_info),
        joinedload(Package.package_property),
    ).all()

    result: List[Dict[str, Any]] = []
    for p in packages:
        prop = p.package_property
        result.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "price_usdt": str(p.price_usdt),
                "description": p.package_description,  # данные из PackageInfo
                # Свойства пакета, если они есть
                "term_months": prop.term_months if prop else None,
                "interest_rate_from": str(prop.interest_rate_from) if prop else None,
                "interest_rate_to": str(prop.interest_rate_to) if prop else None,
                "bonuses": prop.bonuses if prop else None,
                "target_audience": prop.target_audience if prop else None,
            },
        )
    return result


def list_packages_no_price() -> List[Dict[str, Any]]:
    """
    Получает список всех пакетов без поля цены.

    Используется для анонимных пользователей (без токена).
    """
    packages: List[Package] = Package.query.options(
        joinedload(Package.package_info),
        joinedload(Package.package_property),
    ).all()

    result: List[Dict[str, Any]] = []
    for p in packages:
        prop = p.package_property
        result.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "price_usdt": None,  # или просто не включать ключ
                "description": p.package_description,
                "term_months": prop.term_months if prop else None,
                "interest_rate_from": str(prop.interest_rate_from) if prop else None,
                "interest_rate_to": str(prop.interest_rate_to) if prop else None,
                "bonuses": prop.bonuses if prop else None,
                "target_audience": prop.target_audience if prop else None,
            },
        )
    return result


@lru_cache(maxsize=1)
def gas_table() -> Dict[str, Decimal]:
    """
    Создает и кэширует таблицу газовых цен для всех сетей.

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


def check_or_create_purchase(user: User, package_id: int, network: str) -> PurchaseResult:
    """
    Проверяет наличие ожидающей покупки или создает новую.

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
        user_id=user.id, status=PurchaseStatus.pending, network=network).first()

    if pending_purchase:
        logger.info(
            f"Найдена ожидающая покупка {pending_purchase.id} для пользователя {user.id} в сети {network}")
        return {"purchase": pending_purchase, "from_database": True}

    pkg = Package.query.get(package_id)
    if not pkg:
        logger.error(f"Пакет с id {package_id} не найден")
        raise PackageNotFoundError(f"Package with id {package_id} not found")

    # fee = gas_table().get(network)
    # if fee is None:
    #     logger.error(f"Сеть {network} не найдена в таблице газовых цен")
    #     raise NetworkNotFoundError(f"Network {network} not found")

    # total = pkg.price_usdt + fee

    # ТУТ ДОЛЖЕН БЫТЬ МЕХАНИЗМ ПРОВЕРКИ БАЛАНСА В РАНТАЙМЕ

    # check_balance(user, network, total)

    new_purchase = create_purchase(user, pkg, network)
    return {"purchase": new_purchase, "from_database": False}


def create_purchase(user: User, pkg: Package, network: str) -> Purchase:
    """
    Создает новую покупку с статусом 'pending' и сохраняет в базе.

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
    # ПОЛУЧЕНИЕ И РАССЧЕТ ЦЕНЫ ГАЗА ИЗ РАНТАЙМА + МОЖНО В КОРОТКИЙ КЭШ ПИХНУТЬ НА БУДУЩЕЕ
    if fee is None:
        logger.error(
            f"Сеть {network} не найдена в таблице газовых цен при создании покупки")
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
            f"Создана покупка {purchase.id} для пользователя {user.id}")

    return purchase


def process_purchase_confirmation(purchase_id: int, success: bool) -> Purchase:
    """
    Обрабатывает подтверждение или отмену покупки пакета.

    Аргументы:
        purchase_id (int): ID покупки для обработки.
        success (bool): Результат оплаты, True — оплата прошла, False — отмена.

    Возвращает:
        Purchase: Обновленный объект покупки с новым статусом.

    Исключения:
        ValueError: Если покупка не найдена или её статус не подходит для обработки.
    """
    p = Purchase.query.get(purchase_id)
    if not p:
        raise ValueError(f"Purchase with id {purchase_id} not found")

    if success:
        if p.status != PurchaseStatus.pending:
            raise ValueError(
                f"Purchase {purchase_id} status is not pending, current status: {p.status}")

        # ВОТ ТУТ УЖЕ БЛОКИРУЕМ СЧЕТ ПОЛЬЗОВАТЕЛЯ ЧТОБЫ НАС НЕ ЗАСКАМИЛИ НА ГАЗ
        #

        # Создаем транзакцию для покупки
        t = Transaction(
            user_id=p.user_id,
            package_id=p.package_id,
            amount_usdt=p.amount_usdt,
            network=p.network,  # Добавлено поле network
            status="pending",
            # другие поля транзакции при необходимости
        )
        with db.session.begin():
            db.session.add(t)
            # Обновляем статус покупки
            p.status = PurchaseStatus.confirmed
            db.session.add(p)

        # Отправляем уведомление по email (пример)
        user = p.user
        if user:
            email_service = EmailService(db.session)
            context = {
                "user": user,
                "purchase": p,
                "transaction": t,
            }
            try:
                email_service.send_email(
                    to=user.email,
                    subject="Подтверждение покупки пакета",
                    template="purchase_package_notification.html",
                    context=context,
                )
                logging.info(f"Email sent to {user.email} for purchase {p.id}")
            except Exception as e:
                logging.error(f"Failed to send email to {user.email}: {e}")
        else:
            logging.warning(f"User not found for purchase {p.id}")

        # Отправляем событие в Kafka
        send_purchase_event_to_kafka(p, success)

    else:
        # Отмена покупки
        if p.status != PurchaseStatus.pending:
            raise ValueError(
                f"Purchase {purchase_id} status is not pending, current status: {p.status}")

        p.status = PurchaseStatus.canceled
        with db.session.begin():
            db.session.add(p)

        # Отправляем событие в Kafka для отмены
        send_purchase_event_to_kafka(p, success)

    return p


def send_purchase_event_to_kafka(purchase: Purchase, success: bool) -> None:
    """
    Отправляет событие в Kafka о завершении покупки.

    Args:
        purchase (Purchase): Объект покупки, содержащий информацию о завершенной покупке.
        success (bool): Указывает, была ли транзакция успешной.

    Exceptions:
        Exception: Если возникает ошибка при отправке события в Kafka.

    Returns:
        None
    """
    try:
        kfk.send(
            "purchase.completed",
            {
                "purchase_id": purchase.id,
                "user_id": purchase.user_id,
                "amount": str(purchase.amount_usdt),
                # ТУТ НУЖНО ДОБАВИТЬ ПОЛУЧИВШУЮСЯ СТОИМОСТЬ ПАКЕТА ПОСЛЕ ВЫЧЕТА ГАЗА
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
            f"Ошибка при отправке события Kafka для покупки {purchase.id}: {e}")
        raise  # Можно выбросить исключение, чтобы обработать его на уровне API


def check_transaction_status(network: str, tx_id: str) -> bool:  # noqa: PLR0911
    """
    Проверяет статус транзакции в указанной сети по идентификатору.

    Args:
        network (str): Название сети ("ERC20", "BEP20", "TRC20").
        tx_id (str): Идентификатор транзакции, статус которой необходимо проверить.

    Exceptions:
        Exception: Если возникает ошибка при проверке статуса транзакции.

    Returns:
        bool: Возвращает True, если транзакция подтверждена, иначе False.
    """
    try:
        if network in ["ERC20", "BEP20"]:
            # Используем Web3 для ERC20 и BEP20
            receipt = Web3.eth.get_transaction_receipt(tx_id)
            if receipt is None:
                logger.warning(
                    f"Транзакция {tx_id} еще не подтверждена или не найдена.")
                return False
            return receipt.status == 1  # Статус 1 означает успех

        elif network == "TRC20":
            # Используем клиент из провайдера
            tx_info = TRC20.client.get_transaction(tx_id)
            if not tx_info:
                logger.warning(f"Информация о транзакции {tx_id} не найдена.")
                return False

            receipt = tx_info.get("receipt")
            if receipt:
                result = receipt.get("result")
                if result == "SUCCESS":
                    return True
                else:
                    logger.warning(f"Транзакция {tx_id} не успешна: {result}")
                    return False
            else:
                contract_ret = tx_info.get("contractRet")
                if contract_ret == "SUCCESS":
                    return True
                else:
                    logger.warning(
                        f"Транзакция {tx_id} не успешна: {contract_ret}")
                    return False

        else:
            logger.error(f"Неизвестная сеть для проверки: {network}")
            return False

    except Exception as e:
        logger.error(f"Ошибка при проверке статуса транзакции {tx_id}: {e}")
        return False


def confirm_transaction(transaction: Transaction) -> bool:  # noqa: PLR0911
    """
    Подтверждает транзакцию, выполняя перевод средств и проверяя подтверждение.

    Args:
        transaction (Transaction): Объект транзакции, содержащий информацию о переводе.

    Exceptions:
        InsufficientBalanceError: Если недостаточно средств для выполнения транзакции.
        Exception: Если возникает ошибка при подтверждении транзакции.

    Returns:
        bool: Возвращает True, если транзакция успешно подтверждена, иначе False.
    """
    network = transaction.network
    amount = transaction.amount
    user_id = transaction.user_id  # Получаем ID пользователя из транзакции

    # Получаем кошелек пользователя для указанной сети
    wallet = Wallet.query.filter_by(user_id=user_id, network=network).first()
    if not wallet:
        logger.error(
            f"Кошелек для пользователя {user_id} в сети {network} не найден")
        return False

    # Дешифруем приватный ключ кошелька
    try:
        user_private_key = Wallet.decrypt_pk(wallet.pk_enc)  # noqa: F841
    except Exception as e:
        logger.error(f"Ошибка при дешифровании приватного ключа: {e}")
        return False

    to_address = wallet.address  # Адрес для перевода средств
    logger.info(f"Отправка средств на адрес {to_address}")

    try:
        tx_id = ProviderManager.get(network.lower())  # noqa: F841
        if not tx_id:
            logger.error(f"Неизвестная сеть: {network}")
            return False

        # Проверка статуса транзакции с несколькими попытками (до 5 попыток по 10 секунд)
        max_retries = 5
        delay_seconds = 10
        for attempt in range(max_retries):
            time.sleep(delay_seconds)
            if check_transaction_status(network, tx_id):
                logger.info(f"Транзакция {tx_id} подтверждена")
                # Отправка письма об успешной покупке пакета
                user = User.query.get(user_id)
                if user:
                    email_service = EmailService(db.session)
                    context = {
                        "user_uid": user.uid,
                        "subject": "Покупка пакета успешно подтверждена",
                        "user_email": user.email,
                        "amount": amount,
                        "network": network,
                        "transaction_id": tx_id,
                        # добавьте другие данные, если нужны в шаблоне
                    }
                    email_service.send_and_log(
                        to=user.email,
                        template_type="purchase_package_notification.html",
                        context=context,
                    )
                else:
                    logger.warning(
                        f"Пользователь с id {user_id} не найден для отправки уведомления")

                return True
            else:
                logger.info(
                    f"Ожидание подтверждения транзакции {tx_id} (попытка {attempt + 1})")

        logger.warning(f"Транзакция {tx_id} не подтверждена после ожидания")
        return False

    except InsufficientBalanceError as e:
        logger.error(f"Недостаточно средств для транзакции: {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при подтверждении транзакции: {e}")
        return False
