import base64

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _normalize_key(raw: str) -> bytes:
    """Accept raw 32 bytes or already base64-urlsafe 44-char string"""
    if not raw:
        raw = "dev-fernet-key-32bytes________"
    b = raw.encode() if isinstance(raw, str) else raw
    if len(b) == 32:
        return base64.urlsafe_b64encode(b)
    if len(b) == 44 and all(
        c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" or c == 61 for c in b
    ):
        return b
    # Fallback (dev only)
    b = (raw + "_" * 32)[:32].encode()
    return base64.urlsafe_b64encode(b)


def get_fernet() -> Fernet:
    """Возвращает объект Fernet с ключом из конфига."""
    key = current_app.config.get("SECURITY_FERNET_KEY")
    return Fernet(_normalize_key(key))


def encrypt_str(plaintext: str) -> str:
    """Шифрует строку и возвращает base64-строку."""
    f = get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_str(ciphertext: str) -> str:
    """Дешифрует base64-строку, возвращает исходную строку."""
    f = get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Invalid encryption token")
