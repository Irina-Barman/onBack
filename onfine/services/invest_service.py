from decimal import Decimal
from ..extensions import db
from ..models.mining_equipment import MiningEquipment
from ..models.equipment_investment import EquipmentInvestment
from ..models.transactions import Transaction, TxType, TxStatus
from ..utils.ledger_decorator import ledger, LedgerType
from ..services import wallet_service as wsvc


@ledger(LedgerType.purchase, direction="out")          # инвестиция = покупка
def invest(user, equipment_id: int, gross_amount: Decimal):
    """
    Пользователь вкладывает деньги в оборудование.
    50 % уходит на рефералку, 50 % = net инвестиция.
    """
    equip = MiningEquipment.query.get(equipment_id)
    if not equip:
        raise ValueError("Equipment not found")

    net = gross_amount / 2                    # после рефералок
    if wsvc.balance_for(user, "erc") < gross_amount:   # пример сеть ERC
        raise ValueError("Insufficient balance")

    # списываем полную сумму со счёта пользователя
    wsvc.debit(user, "erc", gross_amount)

    inv = EquipmentInvestment.query.filter_by(
            user_id=user.id, equipment_id=equipment_id).first()
    if not inv:
        inv = EquipmentInvestment(user_id=user.id,
                                   equipment_id=equipment_id,
                                   net_amount=net)
        db.session.add(inv)
    else:
        inv.net_amount += net
    db.session.commit()
    return inv
