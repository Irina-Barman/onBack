import base64
import io

import pyotp
import qrcode
from flask import current_app


def generate_base32_secret() -> str:
    """Генерирует новый секрет в base32 для TOTP."""
    return pyotp.random_base32()


def totp_obj(secret: str) -> pyotp.TOTP:
    """Создаёт объект TOTP с настройками из конфига."""
    current_app.config.get("TOTP_WINDOW", 1)
    return pyotp.TOTP(secret)


def provisioning_uri(secret: str, email: str) -> str:
    """Генерирует otpauth URL для настройки 2FA в приложении."""
    issuer = current_app.config.get("TOTP_ISSUER", "Onfine")
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Проверяет TOTP-код с учётом окна допустимости."""
    t = totp_obj(secret)
    return t.verify(code, valid_window=current_app.config.get("TOTP_WINDOW", 1))


def qr_png_bytes(data: str) -> bytes:
    """Генерирует PNG QR-код для otpauth URL."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_url(data: str) -> str:
    """Генерирует data URL PNG QR-кода для otpauth URL."""
    raw = qr_png_bytes(data)
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
