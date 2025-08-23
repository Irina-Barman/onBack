import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from onfine.extensions import db
from onfine.models.wallet_lock import WalletLock, WalletLockPurpose, WalletLockStatus


class WalletLockedError(Exception):
    pass


@contextmanager
def lock_wallet(  # noqa: ANN201
    wallet_id: int,
    purpose: WalletLockPurpose,
    ttl_seconds: int = 60,
    comment: str | None = None,
):  # noqa: ANN201
    """
    Короткий DB-лок на запись кошелька (один активный лок на кошелёк).
    Держим его только на критические секции (секунды).
    """
    token = uuid.uuid4()
    lock = WalletLock(
        wallet_id=wallet_id,
        purpose=purpose,
        holder_token=token,
        status=WalletLockStatus.active,
        ttl_until=datetime.utcnow() + timedelta(seconds=ttl_seconds),  # noqa: DTZ003
        comment=comment,
    )
    try:
        db.session.add(lock)
        db.session.flush()  # пробуем вставить; если нарушится partial-unique — будет IntegrityError
    except IntegrityError:
        db.session.rollback()
        raise WalletLockedError(f"Wallet {wallet_id} is already locked")

    try:
        yield str(token)
        # успешное завершение — снимаем лок
        lock.status = WalletLockStatus.released
        lock.released_at = datetime.utcnow()  # noqa: DTZ003
        db.session.commit()
    except Exception:
        # если упали — тоже снимем лок (или оставим expired по крону)
        db.session.rollback()
        lock = db.session.get(WalletLock, lock.id)
        if lock:
            lock.status = WalletLockStatus.released
            lock.released_at = datetime.utcnow()  # noqa: DTZ003
            db.session.commit()
        raise
