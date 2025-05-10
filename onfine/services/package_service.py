from decimal import Decimal
from typing import Dict, List

from ..extensions import db
from ..models.network_gas import NetworkGas
from ..models.package import Package
from ..models.purchase import Purchase, PurchaseStatus
from ..models.user import User
from ..services import wallet_service as wsvc
from ..utils import kafka_producer as kfk
from ..utils.ledger_decorator import LedgerType, ledger


def list_packages() -> List[Package]:
    """
    Возвращает список всех доступных пакетов.

    :return: Список объектов Package.
    """
    return Package.query.all()


def gas_table() -> Dict[str, Decimal]:
    """
    Создает таблицу газовых (комиссия/транзакция) цен для различных сетей.

    :return: Словарь, где ключами являются названия сетей,
    а значениями - цены газа в USDT.
    """
    return {r.network: Decimal(r.gas_usdt) for r in NetworkGas.query.all()}


@ledger(LedgerType.purchase, direction="out", network_from_arg="network")
def create_purchase(user: User, package_id: int, network: str) -> Purchase:
    """
    Создает покупку пакета для пользователя.

    :param user: Пользователь, который делает покупку.
    :param package_id: Идентификатор пакета.
    :param network: Название сети, в которой осуществляется покупка.
    :raises ValueError: Если пакет не найден или недостаточно средств.
    :return: Объект Purchase, представляющий сделанную покупку.
    """
    pkg = Package.query.get(package_id)
    if not pkg:
        raise ValueError("Package not found")

    fee = gas_table()[network]
    if fee is None:
        raise ValueError("Network not found")  # Добавлено
    total = pkg.price_usdt

    if wsvc.balance_for(user, network) < total:
        raise ValueError("Insufficient balance")

    wsvc.debit(user, network, total)

    purchase = Purchase(
        user=user,
        package=pkg,
        amount_usdt=pkg.price_usdt,
        gas_usdt=fee,
        network=network,
    )
    db.session.add(purchase)
    db.session.commit()
    return purchase


def confirm_purchase(purchase_id: int, success: bool) -> Purchase:
    """
    Подтверждает статус покупки.

    :param purchase_id: Идентификатор покупки.
    :param success: Булевое значение, указывающее на успех операции.
    :raises ValueError: Если покупка не найдена.
    :return: Объект Purchase с обновленным статусом.
    """
    p = Purchase.query.get(purchase_id)
    if not p:
        raise ValueError("Purchase not found")

    p.status = PurchaseStatus.completed if success else PurchaseStatus.canceled
    db.session.commit()

    if success:
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

    return p
