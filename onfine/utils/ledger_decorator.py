"""
Декоратор @ledger – автоматическая запись в таблицу ledger_entries
при успешном выполнении функции-обёртки.
"""
from decimal import Decimal
from functools import wraps
from typing import Callable, Optional

from ..extensions import db
from ..models.ledger_entry import LedgerEntry, LedgerType


def ledger(
    ledger_type: LedgerType,
    *,
    direction: str,
    network_from_arg: Optional[str] = None,
    amount_from_arg: Optional[str] = None,
):
    """
    Пример использования:

        @ledger(LedgerType.withdraw, direction="out",
                network_from_arg="network",
                amount_from_arg="amount")
        def withdraw_funds(user, network, amount, dest, twofa_code): ...

    • origin_table / origin_id берутся из объекта-результата (`return`) –
      он должен иметь атрибуты __tablename__ и id (модели SQLAlchemy).
    • user_id определяется из kwargs['user'] или args[0] (если он модель User).
    """
    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)

            try:
                user   = kwargs.get("user") or (args[0] if args else None)
                user_id = getattr(user, "id", None)

                origin_table = getattr(result, "__tablename__", "")
                origin_id    = getattr(result, "id", 0)

                # amount
                if amount_from_arg and amount_from_arg in kwargs:
                    amount = Decimal(kwargs[amount_from_arg])
                else:
                    amount = Decimal(getattr(result, "amount", "0"))

                # network
                if network_from_arg and network_from_arg in kwargs:
                    network = kwargs[network_from_arg]
                else:
                    network = getattr(result, "network", None)

                entry = LedgerEntry(
                    user_id=user_id,
                    origin_table=origin_table,
                    origin_id=origin_id,
                    type=ledger_type,
                    direction=direction,
                    network=network,
                    amount=amount,
                    meta={},
                )
                db.session.add(entry)
                db.session.commit()
            except Exception as e:      # не рушим бизнес-логику
                db.session.rollback()
                print(f"[LEDGER] failed: {e}")

            return result
        return wrapper
    return decorator


