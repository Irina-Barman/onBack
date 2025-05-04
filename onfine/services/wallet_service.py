"""
onfine/services/wallet_service.py
--------------------------------
Высоко-уровневый сервис работы с кошельками и финансами пользователя:
* генерация trio-кошельков (ERC/BEP/TRC);
* хранение приватного ключа зашифрованным (Fernet);
* вывод средств (MVP-вариант: реальный вызов transfer + запись pending Tx);
* расчёт «псевдо-баланса» на основе подтверждённых депозитов/выводов;
* история транзакций.

Все публичные функции используются REST-namespace-ом
onfine/api/wallet_api.py.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List

from ..extensions import db
from ..blockchain.providers import ERC20, BEP20, TRC20
from ..models.user import User
from ..models.wallet import Wallet
from ..models.transfer_fee import TransferFee
from ..models.transactions import Transaction, TxType, TxStatus
from ..utils.ledger_decorator import ledger, LedgerType
from ..models.referral_balance import ReferralBalance
from ..models.ledger_entry import LedgerEntry


NETWORKS: tuple[str, ...] = ("bep", "erc", "trc")


# ───────── helpers
def _gen_addr_pk(network: str) -> tuple[str, str]:
    if network == "erc":
        return ERC20.generate_wallet()
    if network == "bep":
        return BEP20.generate_wallet()
    if network == "trc":
        return TRC20.generate_wallet()
    raise ValueError("Unknown network")


# ───────── wallet CRUD
def create_wallets(user: User) -> Dict[str, str]:
    existing = {w.network: w.address for w in user.wallets}

    for net in NETWORKS:
        if net not in existing:
            addr, pk = _gen_addr_pk(net)
            w = Wallet(
                user_id=user.id,
                network=net,
                address=addr,
                pk_enc=Wallet.encrypt_pk(pk),
            )
            db.session.add(w)
            existing[net] = addr

    db.session.commit()
    return existing


def list_wallets(user: User) -> Dict[str, str] | None:
    rows = {w.network: w.address for w in user.wallets}
    return rows or None


# ───────── fees / balance
def transfer_fee_table() -> Dict[str, Decimal]:
    return {r.network: Decimal(r.fee_usdt) for r in TransferFee.query.all()}


def user_balance_stub(user: User) -> Dict[str, Decimal]:
    res: Dict[str, Decimal] = {}
    for net in NETWORKS:
        deposits = (
            db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0))
            .filter_by(user_id=user.id, network=net,
                       type=TxType.deposit, status=TxStatus.confirmed)
            .scalar()
        )
        withdraws = (
            db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0))
            .filter_by(user_id=user.id, network=net,
                       type=TxType.withdraw, status=TxStatus.confirmed)
            .scalar()
        )
        res[f"{net}_balance"] = Decimal(deposits) - Decimal(withdraws)
    return res


# ───────── history
def history(user: User) -> List[Transaction]:
    return (
        Transaction.query.filter_by(user_id=user.id)
        .order_by(Transaction.created_at.desc())
        .all()
    )


def balance_for(user: User, network: str) -> Decimal:
    return user_balance_stub(user)[f"{network}_balance"]


@ledger(LedgerType.purchase, direction="out",
        network_from_arg="network", amount_from_arg="amount")
def debit(user: User, network: str, amount: Decimal) -> Transaction:
    tx = Transaction(
        user_id=user.id,
        type=TxType.purchase,
        status=TxStatus.confirmed,
        network=network,
        amount=amount,
    )
    db.session.add(tx)
    db.session.commit()
    return tx


@ledger(LedgerType.withdraw, direction="out",
        network_from_arg="network", amount_from_arg="amount")
def withdraw_funds(user: User, network: str, amount: Decimal,
                   dest: str, twofa_code: str) -> Transaction:
    if network not in NETWORKS:
        raise ValueError("Unknown network")
    if twofa_code != "123456":
        raise ValueError("Invalid 2FA")

    fee = transfer_fee_table()[network]
    total = amount + fee

    if balance_for(user, network) < total:
        raise ValueError("Insufficient balance")

    wallet = next((w for w in user.wallets if w.network == network), None)
    if not wallet:
        raise ValueError("Wallet not found")

    pk = Wallet.decrypt_pk(wallet.pk_enc)

    tx_hash = {
        "erc": lambda: ERC20.transfer(pk, dest, amount),
        "bep": lambda: BEP20.transfer(pk, dest, amount),
        "trc": lambda: TRC20.transfer(pk, dest, amount),
    }[network]()

    tx = Transaction(
        user_id=user.id,
        type=TxType.withdraw,
        status=TxStatus.pending,
        network=network,
        amount=amount,
        fee=fee,
        address=dest,
    )
    db.session.add(tx)
    db.session.commit()
    print(f"[WITHDRAW] {network} hash={tx_hash}")
    return tx


def ref_balance(user: User) -> Decimal:
    rb = ReferralBalance.query.get(user.id)
    return Decimal(rb.balance) if rb else Decimal(0)


def ref_credit(user_id: int, amount: Decimal):
    rb = ReferralBalance.query.get(user_id)
    if not rb:
        rb = ReferralBalance(user_id=user_id, balance=amount)
        db.session.add(rb)
    else:
        rb.balance += amount
    db.session.flush()


@ledger(LedgerType.referral, direction="out")        # отрицательное списание
def ref_debit(user: User, amount: Decimal) -> Transaction:
    rb = ReferralBalance.query.get(user.id)
    if not rb or rb.balance < amount:
        raise ValueError("Not enough referral balance")
    rb.balance -= amount
    tx = Transaction(
        user_id=user.id, type=TxType.referral,
        status=TxStatus.confirmed, network="ref",
        amount=-amount
    )
    db.session.add(tx)
    db.session.flush()
    return tx


@ledger(LedgerType.purchase, direction="out",
        network_from_arg="network", amount_from_arg="amount")
def credit_to_balance(user: User, network: str, amount: Decimal) -> Transaction:
    tx = Transaction(
        user_id=user.id,
        type=TxType.profit,
        status=TxStatus.confirmed,
        network=network,
        amount=amount,
    )
    db.session.add(tx)
    db.session.commit()
    return tx


def credit_to_balance(user_id: int, network: str, amount: Decimal):
    tx = Transaction(
        user_id=user_id, type=TxType.deposit,
        status=TxStatus.confirmed, network=network, amount=amount)
    db.session.add(tx); db.session.flush()
    db.session.add(LedgerEntry(
        user_id=user_id, origin_table="transactions", origin_id=tx.id,
        type=LedgerType.deposit, direction="in",
        network=network, amount=amount))
    db.session.commit()
