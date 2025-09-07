"""
Сервис управления двухфакторной аутентификацией (2FA) с использованием TOTP и резервных кодов.

Основные функции:
- Гарантирование наличия секрета для TOTP.
- Генерация данных для настройки 2FA (otpauth URL и QR-код).
- Генерация PNG QR-кода для 2FA.
- Включение 2FA с проверкой кода.
- Безопасное отключение 2FA с проверкой пароля и кода.
- Проверка TOTP-кода при логине.
- Генерация и сохранение резервных кодов.
- Проверка и использование резервного кода.

Используемые компоненты:
- Модель: User.
- SQLAlchemy (db) для работы с базой данных.
- Модули: werkzeug.security для хэширования, onfine.security.crypto для
    шифрования/дешифрования, onfine.security.totp для работы с TOTP.
- JSON для хранения хэшей резервных кодов.
- Secrets для генерации случайных кодов.

Функции:

ensure_secret(user: User) -> Tuple[str, bool]
    Гарантирует наличие секрета для TOTP. Возвращает секрет и флаг,
    указывающий, был ли создан новый.

provisioning(user: User) -> dict
    Генерирует данные для настройки 2FA в приложении (otpauth URL и QR-код).

provisioning_png(user: User) -> bytes
    Генерирует PNG QR-код для 2FA.

enable(user: User, code: str) -> bool
    Включает 2FA, если предоставленный TOTP-код валиден.

disable_secure(user: User, password: str, code: Optional[str] = None,
backup_code: Optional[str] = None) -> bool
    Безопасно отключает 2FA с проверкой пароля и TOTP-кода или резервного кода.

verify_login(user: User, code: str) -> bool
    Проверяет TOTP-код при логине. Возвращает True, если код верен или 2FA не включена.

generate_backup_codes(user: User, count: int = 10) -> List[str]
    Генерирует и сохраняет новый набор резервных кодов. Возвращает список кодов.

use_backup_code(user: User, code: str) -> bool
    Проверяет и использует (удаляет) резервный код.
"""

import json
import secrets
from typing import List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from onfine.extensions import db
from onfine.models.user import User
from onfine.security.crypto import decrypt_str, encrypt_str
from onfine.security.totp import (
    generate_base32_secret,
    provisioning_uri,
    qr_data_url,
    qr_png_bytes,
    verify_totp,
)


class TwoFAService:
    @staticmethod
    def ensure_secret(user: User) -> Tuple[str, bool]:
        """
        Гарантирует, что у пользователя есть секрет для TOTP.

        Args:
            user (User ): Экземпляр пользователя.

        Returns:
            Tuple[str, bool]: Кортеж, содержащий секрет и флаг, указывающий, был ли создан новый секрет.
        """
        if user.totp_secret_enc:
            return decrypt_str(user.totp_secret_enc), False
        secret = generate_base32_secret()
        user.totp_secret_enc = encrypt_str(secret)
        db.session.commit()
        return secret, True

    @staticmethod
    def provisioning(user: User) -> dict:
        """
        Генерирует данные для настройки 2FA в приложении (otpauth URL и QR-код).

        Args:
            user (User ): Экземпляр пользователя.

        Returns:
            dict: Словарь с otpauth_url и qr_data_url для настройки 2FA.
        """
        secret, _ = TwoFAService.ensure_secret(user)
        otpauth = provisioning_uri(secret, user.email)
        return {"otpauth_url": otpauth, "qr_data_url": qr_data_url(otpauth)}

    @staticmethod
    def provisioning_png(user: User) -> bytes:
        """
        Генерирует PNG QR-код для 2FA.

        Args:
            user (User ): Экземпляр пользователя.

        Returns:
            bytes: PNG-изображение QR-кода.
        """
        secret, _ = TwoFAService.ensure_secret(user)
        otpauth = provisioning_uri(secret, user.email)
        return qr_png_bytes(otpauth)

    @staticmethod
    def enable(user: User, code: str) -> bool:
        """
        Включает 2FA, если предоставленный код валиден.

        Args:
            user (User ): Экземпляр пользователя.
            code (str): TOTP-код для проверки.

        Returns:
            bool: True, если 2FA успешно включена, иначе False.
        """
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
        Безопасно отключает 2FA.

        Проверяет пароль пользователя, затем требует валидный TOTP-код ИЛИ резервный код.
        После успешной проверки сбрасывает флаги и стирает секрет и резервные коды.

        Args:
            user (User ): Экземпляр пользователя.
            password (str): Пароль пользователя.
            code (Optional[str]): TOTP-код для проверки.
            backup_code (Optional[str]): Резервный код для проверки.

        Returns:
            bool: True, если 2FA успешно отключена, иначе False.
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
        """
        Проверяет TOTP-код при логине.

        Args:
            user (User ): Экземпляр пользователя.
            code (str): TOTP-код для проверки.

        Returns:
            bool: True, если код верен или 2FA не включена, иначе False.
        """
        if not user.is_2fa_enabled:
            return True
        if not user.totp_secret_enc:
            return False
        secret = decrypt_str(user.totp_secret_enc)
        return verify_totp(secret, code)

    @staticmethod
    def generate_backup_codes(user: User, count: int = 10) -> List[str]:
        """
        Генерирует и сохраняет в БД новый набор резервных кодов.

        Args:
            user (User ): Экземпляр пользователя.
            count (int): Количество резервных кодов для генерации (по умолчанию 10).

        Returns:
            List[str]: Список сгенерированных резервных кодов.
        """
        codes = [secrets.token_urlsafe(8) for _ in range(count)]
        hashes = [generate_password_hash(c) for c in codes]
        user.backup_codes_hash = json.dumps(hashes)
        db.session.commit()
        return codes

    @staticmethod
    def use_backup_code(user: User, code: str) -> bool:
        """
        Проверяет и использует (удаляет) резервный код.

        Args:
            user (User ): Экземпляр пользователя.
            code (str): Резервный код для проверки.

        Returns:
            bool: True, если код валиден и использован, иначе False.
        """
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
