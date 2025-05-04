from decimal import Decimal
from typing import List

from ..extensions import db
from ..models.package import Package
from ..models.purchase import Purchase, PurchaseStatus
from ..models.network_gas import NetworkGas
from ..models.user import User
from ..utils.ledger_decorator import ledger, LedgerType
from ..services import wallet_service as wsvc
from ..utils import kafka_producer as kfk


def list_packages() -> List[Package]:
    return Package.query.all()


def gas_table() -> dict[str, Decimal]:
    return {r.network: Decimal(r.gas_usdt) for r in NetworkGas.query.all()}


@ledger(LedgerType.purchase, direction="out", network_from_arg="network")
def create_purchase(user: User, package_id: int, network: str) -> Purchase:
    pkg = Package.query.get(package_id)
    if not pkg:
        raise ValueError("Package not found")

    fee = gas_table()[network]
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
    p = Purchase.query.get(purchase_id)
    if not p:
        raise ValueError("Purchase not found")

    p.status = PurchaseStatus.completed if success else PurchaseStatus.canceled
    db.session.commit()

    if success:
        kfk.send("purchase.completed", {
            "purchase_id": p.id,
            "user_id": p.user_id,
            "amount": str(p.amount_usdt),
            "partner_uid": p.user.partner_uid,
            "network": p.network,
            "program_type": 1,
            "ts": p.created_at.isoformat()
        })

    return p


