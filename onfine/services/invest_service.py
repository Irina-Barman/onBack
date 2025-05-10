from decimal import Decimal
from typing import Any

from ..extensions import db
from ..models.equipment_investment import EquipmentInvestment
from ..models.mining_equipment import MiningEquipment
from ..services import wallet_service as wsvc
from ..utils.ledger_decorator import LedgerType, ledger


@ledger(LedgerType.purchase, direction="out")  # инвестиция = покупка
def invest(
    user: Any,
    equipment_id: int,
    gross_amount: Decimal,
) -> EquipmentInvestment:
    """
    Пользователь вкладывает деньги в оборудование.
    50 % уходит на рефералку, 50 % = net инвестиция.

    :param user: Пользователь, который делает инвестицию.
    :param equipment_id: Идентификатор оборудования, в которое инвестируют.
    :param gross_amount: Общая сумма инвестиции.
    :raises ValueError: Если оборудование не найдено или
    баланс пользователя недостаточен.
    :return: Объект EquipmentInvestment, представляющий сделанную инвестицию.
    """
    equip = MiningEquipment.query.get(equipment_id)
    if not equip:
        raise ValueError("Equipment not found")

    net = gross_amount / 2  # после рефералок
    if wsvc.balance_for(user, "erc") < gross_amount:  # пример сеть ERC
        raise ValueError("Insufficient balance")

    # списываем полную сумму со счёта пользователя
    wsvc.debit(user, "erc", gross_amount)

    inv = EquipmentInvestment.query.filter_by(
        user_id=user.id, equipment_id=equipment_id
    ).first()
    if not inv:
        inv = EquipmentInvestment(
            user_id=user.id, equipment_id=equipment_id, net_amount=net
        )
        db.session.add(inv)
    else:
        inv.net_amount += net
    db.session.commit()
    return inv
