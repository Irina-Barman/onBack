import decimal
import hashlib
import hmac
import os
import time
from typing import Any, Dict

import requests

decimal.getcontext().prec = 28

_KEY, _SEC = os.getenv("EMCD_KEY"), os.getenv("EMCD_SECRET").encode()
_BASE = "https://api.emcd.io/v1"


def _sign(p: str, ts: str) -> str:
    """
    Создает HMAC-подпись для запроса.

    Args:
        p (str): Путь запроса.
        ts (str): Временная метка.

    Returns:
        str: HMAC-подпись.
    """
    return hmac.new(_SEC, f"{ts}{p}".encode(), hashlib.sha256).hexdigest()


def _get(path: str) -> Dict[str, Any]:
    """
    Отправляет GET-запрос к API и возвращает данные.

    Args:
        path (str): Путь запроса.

    Returns:
        Dict[str, Any]: Ответ API в формате JSON.

    Raises:
        requests.HTTPError: Если запрос завершился с ошибкой.
    """
    ts = str(int(time.time()))
    r = requests.get(
        _BASE + path,
        headers={
            "X-Api-Key": _KEY,
            "X-Api-Timestamp": ts,
            "X-Api-Sign": _sign(path, ts),
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]


def get_today_income_usdt() -> decimal.Decimal:
    """
    Получает доход за сегодня в USDT.

    Returns:
        decimal.Decimal: Доход за сегодня.
    """
    d = _get("/account/balance/history?days=1")[0]
    return decimal.Decimal(d["amount"])
