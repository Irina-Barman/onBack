from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError

from onfine.extensions import db
from onfine.models.wallet_lock import WalletLock, WalletLockPurpose, WalletLockStatus


class WalletLockedError(Exception):
    """Кошелёк уже залочен активным локом (и TTL не истёк)."""


def _now() -> datetime:
    return datetime.utcnow()  # noqa: DTZ003


def is_wallet_locked(wallet_id: int) -> bool:
    """
    Быстрая проверка: есть ли активный, не истёкший лок.
    """
    return db.session.query(
        db.session.query(WalletLock)
        .filter(
            WalletLock.wallet_id == wallet_id,
            WalletLock.status == WalletLockStatus.active,
            (WalletLock.ttl_until.is_(None)) | (WalletLock.ttl_until > _now()),
        )
        .exists(),
    ).scalar()


def acquire_wallet_lock(
    wallet_id: int,
    purpose: WalletLockPurpose,
    ttl_seconds: int = 300,
    comment: Optional[str] = None,
) -> tuple[int, str]:
    """
    Создаёт «долгий» лок: отдельная строка со статусом active и TTL.
    Благодаря partial unique индексу в таблице будет не более одного active-лока на кошелёк.

    Возвращает: (lock_id, holder_token)
    """
    holder_token = uuid.uuid4()
    lock = WalletLock(
        wallet_id=wallet_id,
        purpose=purpose,
        holder_token=holder_token,  # UUID в твоей модели как as_uuid=True
        status=WalletLockStatus.active,
        ttl_until=_now() + timedelta(seconds=ttl_seconds),
        comment=comment,
    )
    try:
        db.session.add(lock)
        db.session.flush()  # тут получим IntegrityError, если уже есть active лок
    except IntegrityError:
        db.session.rollback()
        raise WalletLockedError(f"Wallet {wallet_id} is already locked")

    return lock.id, str(holder_token)


def extend_wallet_lock(lock_id: int, holder_token: str, add_seconds: int = 120) -> None:
    """
    Продлевает TTL активного лока (используй в воркерах, пока ждёшь сеть).
    """
    lock = WalletLock.query.get(lock_id)
    if not lock:
        return
    if lock.status != WalletLockStatus.active:
        return
    if str(lock.holder_token) != str(holder_token):
        return
    lock.ttl_until = _now() + timedelta(seconds=add_seconds)
    db.session.commit()


def release_wallet_lock(lock_id: int, holder_token: str) -> None:
    """
    Снимает лок: переводит в released и проставляет released_at.
    """
    lock = WalletLock.query.get(lock_id)
    if not lock:
        return
    if lock.status != WalletLockStatus.active:
        return
    if str(lock.holder_token) != str(holder_token):
        return
    lock.status = WalletLockStatus.released
    lock.released_at = _now()
    db.session.commit()


@contextmanager
def lock_wallet_short(  # noqa: ANN201
    wallet_id: int,
    purpose: WalletLockPurpose,
    ttl_seconds: int = 60,
    comment: Optional[str] = None,
):  # noqa: ANN201
    """
    КОРОТКИЙ лок на критическую секцию (секунды). Автоснятие по выходу из контекста.
    Не держим тут сетевые ожидания!
    """
    lock_id = None
    token = None
    try:
        lock_id, token = acquire_wallet_lock(wallet_id, purpose, ttl_seconds, comment)
        yield (lock_id, token)
    except Exception:
        db.session.rollback()
        if lock_id and token:
            try:
                release_wallet_lock(lock_id, token)
            except Exception:
                pass
        raise
    else:
        if lock_id and token:
            release_wallet_lock(lock_id, token)


def refresh_lock_if_needed(lock_id: int, holder_token: str, min_left_sec: int = 30, extend_sec: int = 120) -> None:
    """
    Если скоро истечёт TTL — продлеваем. Удобно дёргать каждые N секунд в ожидательных воркерах.
    """
    lock = WalletLock.query.get(lock_id)
    if not lock or lock.status != WalletLockStatus.active or str(lock.holder_token) != str(holder_token):
        return
    if not lock.ttl_until:
        return
    if (lock.ttl_until - _now()).total_seconds() <= min_left_sec:
        extend_wallet_lock(lock_id, holder_token, extend_sec)


def expire_stale_locks(batch_limit: int = 200) -> int:
    """
    Утилита для периодического крона: переводит протухшие active-локи в expired.
    Возвращает количество помеченных как expired.
    """
    q = WalletLock.query.filter(
        WalletLock.status == WalletLockStatus.active,
        WalletLock.ttl_until.isnot(None),
        WalletLock.ttl_until <= _now(),
    ).limit(batch_limit)

    count = 0
    for lock in q:
        lock.status = WalletLockStatus.expired
        count += 1
    if count:
        db.session.commit()
    return count
