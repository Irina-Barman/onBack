"""
Модуль для шифрования и дешифрования строк с использованием Fernet.

Основные функции:
- Нормализация ключа для Fernet.
- Получение объекта Fernet с ключом из конфигурации.
- Шифрование строки в base64-строку.
- Дешифрование base64-строки в исходную строку.

Используемые компоненты:
- cryptography.fernet для шифрования.
- base64 для кодирования ключей.
- flask для доступа к конфигурации приложения.

Функции:

_normalize_key(raw: str) -> bytes
    Нормализует ключ: принимает сырые 32 байта или уже base64-urlsafe 44-символьную строку.

get_fernet() -> Fernet
    Возвращает объект Fernet с ключом из конфигурации приложения.

encrypt_str(plaintext: str) -> str
    Шифрует строку и возвращает base64-строку.

decrypt_str(ciphertext: str) -> str
    Дешифрует base64-строку, возвращает исходную строку. Вызывает ValueError при недействительном токене.

Исключения:
- ValueError при недействительном токене шифрования.
"""

import base64
from typing import Union

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _normalize_key(raw: Union[str, bytes]) -> bytes:
    """
    Нормализует ключ для Fernet.

    Принимает сырые 32 байта или уже base64-urlsafe 44-символьную строку.
    В режиме разработки использует fallback-ключ.

    Args:
        raw (Union[str, bytes]): Сырой ключ.

    Returns:
        bytes: Нормализованный ключ в формате base64-urlsafe.
    """
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
    """
    Возвращает объект Fernet с ключом из конфигурации приложения.

    Returns:
        Fernet: Объект Fernet для шифрования/дешифрования.
    """
    key = current_app.config.get("SECURITY_FERNET_KEY")
    return Fernet(_normalize_key(key))


def encrypt_str(plaintext: str) -> str:
    """
    Шифрует строку и возвращает base64-строку.

    Args:
        plaintext (str): Исходная строка для шифрования.

    Returns:
        str: Зашифрованная строка в формате base64.
    """
    f = get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_str(ciphertext: str) -> str:
    """
    Дешифрует base64-строку, возвращает исходную строку.

    Args:
        ciphertext (str): Зашифрованная строка в формате base64.

    Returns:
        str: Дешифрованная исходная строка.

    Raises:
        ValueError: Если токен недействителен.
    """
    f = get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Invalid encryption token")
