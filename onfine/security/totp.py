"""
Модуль для работы с TOTP (Time-based One-Time Password) и генерацией QR-кодов.

Основные функции:
- Генерация нового секрета в base32 для TOTP.
- Создание объекта TOTP с настройками из конфигурации.
- Генерация otpauth URL для настройки 2FA в приложении.
- Проверка TOTP-кода с учётом окна допустимости.
- Генерация PNG QR-кода для otpauth URL.
- Генерация data URL PNG QR-кода для otpauth URL.

Используемые компоненты:
- pyotp для работы с TOTP.
- qrcode для генерации QR-кодов.
- base64 и io для обработки изображений.
- flask для доступа к конфигурации приложения.

Функции:

generate_base32_secret() -> str
    Генерирует новый секрет в base32 для TOTP.

totp_obj(secret: str) -> pyotp.TOTP
    Создаёт объект TOTP с настройками из конфигурации.

provisioning_uri(secret: str, email: str) -> str
    Генерирует otpauth URL для настройки 2FA в приложении.

verify_totp(secret: str, code: str) -> bool
    Проверяет TOTP-код с учётом окна допустимости.

qr_png_bytes(data: str) -> bytes
    Генерирует PNG QR-код для otpauth URL.

qr_data_url(data: str) -> str
    Генерирует data URL PNG QR-кода для otpauth URL.
"""

import base64
import io

import pyotp
import qrcode
from flask import current_app
from qrcode.image.pil import PilImage


def generate_base32_secret() -> str:
    """
    Генерирует новый секрет в base32 для TOTP.

    Returns:
        str: Секрет в формате base32.
    """
    return pyotp.random_base32()


def totp_obj(secret: str) -> pyotp.TOTP:
    """
    Создаёт объект TOTP с настройками из конфигурации.

    Args:
        secret (str): Секрет в base32.

    Returns:
        pyotp.TOTP: Объект TOTP.
    """
    current_app.config.get("TOTP_WINDOW", 1)
    return pyotp.TOTP(secret)


def provisioning_uri(secret: str, email: str) -> str:
    """
    Генерирует otpauth URL для настройки 2FA в приложении.

    Args:
        secret (str): Секрет в base32.
        email (str): Email пользователя.

    Returns:
        str: otpauth URL.
    """
    issuer = current_app.config.get("TOTP_ISSUER", "Onfine")
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """
    Проверяет TOTP-код с учётом окна допустимости.

    Args:
        secret (str): Секрет в base32.
        code (str): TOTP-код для проверки.

    Returns:
        bool: True, если код валиден, иначе False.
    """
    t = totp_obj(secret)
    return t.verify(code, valid_window=current_app.config.get("TOTP_WINDOW", 1))


def qr_png_bytes(data: str) -> bytes:
    """
    Генерирует PNG QR-код для otpauth URL.

    Args:
        data (str): Данные для QR-кода (например, otpauth URL).

    Returns:
        bytes: PNG-изображение QR-кода.
    """
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(image_factory=PilImage, fill_color="white", back_color="black")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_url(data: str) -> str:
    """
    Генерирует data URL PNG QR-кода для otpauth URL.

    Args:
        data (str): Данные для QR-кода (например, otpauth URL).

    Returns:
        str: Data URL с base64-кодированным PNG QR-кодом.
    """
    raw = qr_png_bytes(data)
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
