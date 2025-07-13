import hashlib

import base58


def from_hex_address(hex_addr: str) -> str:
    """
    Преобразует TRON-адрес из шестнадцатеричной строки (hex) в формат base58check с префиксом сети.

    Аргументы:
        hex_addr (str): Адрес в виде hex-строки, может начинаться с "0x" или "0X".

    Возвращает:
        str: Адрес в формате base58check, начинающийся с 'T'.

    Исключения:
        ValueError: Если входная строка пустая или содержит недопустимые символы.

    Описание:
        - Удаляет префикс "0x" если есть.
        - Проверяет, что строка состоит только из hex символов.
        - Формирует байтовый адрес с префиксом сети TRON mainnet (0x41).
        - Вычисляет двойной sha256 хеш для контрольной суммы.
        - Добавляет первые 4 байта контрольной суммы к адресу.
        - Кодирует итоговый байтовый массив в base58.
    """
    if not hex_addr:
        raise ValueError("Empty hex address string")

    if hex_addr.startswith("0x") or hex_addr.startswith("0X"):
        hex_addr = hex_addr[2:]

    # Проверка, что строка состоит только из hex символов
    if any(c not in "0123456789abcdefABCDEF" for c in hex_addr):
        raise ValueError(f"Invalid hex characters in address: {hex_addr}")

    addr_bytes = bytes.fromhex(hex_addr)
    prefix = b"\x41"  # префикс TRON mainnet
    addr = prefix + addr_bytes[-20:]  # берем последние 20 байт адреса (20 байт - длина адреса TRON)
    hash0 = hashlib.sha256(addr).digest()
    hash1 = hashlib.sha256(hash0).digest()
    checksum = hash1[:4]  # первые 4 байта двойного sha256 - контрольная сумма
    addr_check = addr + checksum
    return base58.b58encode(addr_check).decode()


def normalize_tron_address(addr: str) -> str:
    """
    Нормализует TRON-адрес, приводя его к стандартному формату base58check.

    Аргументы:
        addr (str): Входной адрес, может быть в формате base58check (начинается с 'T') или hex.

    Возвращает:
        str: Адрес в формате base58check (начинается с 'T').

    Исключения:
        ValueError: Если адрес пустой или не может быть нормализован.

    Описание:
        - Если адрес уже в формате base58check (начинается с 'T' и длина 34 символа), возвращает его без изменений.
        - Иначе пытается преобразовать hex-адрес в base58check с помощью from_hex_address.
        - При ошибках выбрасывает исключение с описанием.
    """
    if not addr:
        raise ValueError("Empty address")

    if addr.startswith("T") and len(addr) == 34:
        return addr

    try:
        return from_hex_address(addr)
    except Exception as e:
        raise ValueError(f"Cannot normalize TRON address '{addr}': {e}")
