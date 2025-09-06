import json
import secrets
from typing import List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from onfine.extensions import db
from onfine.models.user import User
from onfine.security.crypto import decrypt_str, encrypt_str
from onfine.security.totp import generate_base32_secret, provisioning_uri, qr_data_url, qr_png_bytes, verify_totp


class TwoFAService:
    @staticmethod
    def ensure_secret(user: User) -> Tuple[str, bool]:
        """Гарантирует, что у пользователя есть секрет для TOTP. Возвращает (secret, created_new)."""
        if user.totp_secret_enc:
            return decrypt_str(user.totp_secret_enc), False
        secret = generate_base32_secret()
        user.totp_secret_enc = encrypt_str(secret)
        db.session.commit()
        return secret, True

    @staticmethod
    def provisioning(user: User) -> dict:
        """Генерирует данные для настройки 2FA в приложении (otpauth URL и QR-код)."""
        secret, _ = TwoFAService.ensure_secret(user)
        otpauth = provisioning_uri(secret, user.email)
        return {"otpauth_url": otpauth, "qr_data_url": qr_data_url(otpauth)}

    @staticmethod
    def provisioning_png(user: User) -> bytes:
        """Генерирует PNG QR-код для 2FA."""
        secret, _ = TwoFAService.ensure_secret(user)
        otpauth = provisioning_uri(secret, user.email)
        return qr_png_bytes(otpauth)

    @staticmethod
    def enable(user: User, code: str) -> bool:
        """
        Включает 2FA, если предоставленный код валиден."""
        secret, _ = TwoFAService.ensure_secret(user)
        if verify_totp(secret, code):
            user.is_2fa_enabled = True
            db.session.commit()
            return True
        return False

    @staticmethod
    def disable_secure(
        user: User,
        password: str,
        code: Optional[str] = None,
        backup_code: Optional[str] = None,
    ) -> bool:
        """
        Безопасно отключает 2FA:
          1) Проверяет пароль пользователя.
          2) Требует валидный TOTP-код ИЛИ резервный код.
          3) Сбрасывает флаги и стирает секрет/резервные коды.
        """
        if not user.check_password(password):
            return False

        if not user.is_2fa_enabled:
            user.totp_secret_enc = None
            user.backup_codes_hash = None
            db.session.commit()
            return True

        verified = False
        if code:
            if not user.totp_secret_enc:
                return False
            secret = decrypt_str(user.totp_secret_enc)
            verified = verify_totp(secret, code)
        elif backup_code:
            if not user.backup_codes_hash:
                return False
            hashes = json.loads(user.backup_codes_hash)
            for i, h in enumerate(hashes):
                if check_password_hash(h, backup_code):
                    # одноразовый — удаляем использованный
                    del hashes[i]
                    user.backup_codes_hash = json.dumps(hashes)
                    verified = True
                    break

        if not verified:
            return False

        user.is_2fa_enabled = False
        user.totp_secret_enc = None
        user.backup_codes_hash = None
        db.session.commit()
        return True

    @staticmethod
    def verify_login(user: User, code: str) -> bool:
        """Проверяет TOTP-код при логине."""
        if not user.is_2fa_enabled:
            return True
        if not user.totp_secret_enc:
            return False
        secret = decrypt_str(user.totp_secret_enc)
        return verify_totp(secret, code)

    # Backup codes
    @staticmethod
    def generate_backup_codes(user: User, count: int = 10) -> List[str]:
        """Генерирует и сохраняет в БД новый набор резервных кодов."""
        codes = [secrets.token_urlsafe(8) for _ in range(count)]
        hashes = [generate_password_hash(c) for c in codes]
        user.backup_codes_hash = json.dumps(hashes)
        db.session.commit()
        return codes

    @staticmethod
    def use_backup_code(user: User, code: str) -> bool:
        """
        Проверяет и использует (удаляет) резервный код."""
        if not user.backup_codes_hash:
            return False
        hashes = json.loads(user.backup_codes_hash)
        for i, h in enumerate(hashes):
            if check_password_hash(h, code):
                del hashes[i]
                user.backup_codes_hash = json.dumps(hashes)
                db.session.commit()
                return True
        return False
