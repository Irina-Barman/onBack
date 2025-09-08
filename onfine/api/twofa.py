from io import BytesIO
from typing import Any, Dict, Tuple

from flask import Response, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services.twofa_service import TwoFAService

ns = Namespace("2fa", description="Two-Factor Authentication", path="/auth/2fa")

twofa_setup = ns.model(
    "TwoFASetup",
    {
        "otpauth_url": fields.String(required=True, description="URL для настройки 2FA в приложении"),
        "qr_data_url": fields.String(required=True, description="QR-код в формате data URL"),
    },
)

enable_in = ns.model(
    "TwoFAEnableIn",
    {
        "code": fields.String(required=True, min_length=6, max_length=6, description="6-значный TOTP-код"),
    },
)

verify_in = ns.model(
    "TwoFAVerifyIn",
    {
        "code": fields.String(required=True, min_length=6, max_length=6, description="6-значный TOTP-код"),
    },
)

backup_use_in = ns.model(
    "BackupUseIn",
    {
        "backup_code": fields.String(required=True, description="Резервный одноразовый код"),
    },
)

disable_in = ns.model(
    "TwoFADisableIn",
    {
        "password": fields.String(required=True, description="Текущий пароль пользователя"),
        "code": fields.String(required=False, description="6-значный TOTP-код"),
        "backup_code": fields.String(required=False, description="Резервный одноразовый код"),
    },
)


@ns.route("/setup")
class TwoFASetup(Resource):
    @jwt_required()
    @ns.marshal_with(twofa_setup, code=200)
    def post(self) -> Tuple[Dict[str, str], int]:
        """
        Генерирует и возвращает данные для настройки двухфакторной аутентификации (2FA).

        Returns:
        Кортеж с данными для настройки 2FA и HTTP статусом 200.

                 Формат данных:
                 {
                    "otpauth_url": str,  # URL для Google Authenticator
                    "qr_data_url": str,  # QR-код в формате data URL
                 }
        """
        user = User.query.get_or_404(get_jwt_identity())
        return TwoFAService.provisioning(user), 200


@ns.route("/qr.png")
class TwoFAQr(Resource):
    @jwt_required()
    def get(self) -> Response:
        """
        Возвращает PNG-изображение QR-кода для настройки 2FA.

        Returns:
        PNG-изображение с QR-кодом для сканирования в приложении.

        Example request:
        curl -X GET "http://127.0.0.1:5500/auth/2fa/qr.png" \
            -H "Authorization: Bearer <your_jwt_token>" \
            --output qr.png
        """
        user = User.query.get_or_404(get_jwt_identity())
        raw = TwoFAService.provisioning_png(user)
        return send_file(BytesIO(raw), mimetype="image/png")


@ns.route("/enable")
class TwoFAEnable(Resource):
    @jwt_required()
    @ns.expect(enable_in, validate=True)
    def post(self) -> Tuple[Dict[str, str], int]:
        """
        Включает двухфакторную аутентификацию для пользователя при корректном TOTP-коде.

        Returns:
        JSON с результатом и HTTP статусом.

                 При успехе: {"status": "enabled"}, 200
                 При ошибке: {"error": "Invalid TOTP code"}, 400
        """
        user = User.query.get_or_404(get_jwt_identity())
        code = request.json.get("code")
        if not TwoFAService.enable(user, code):
            return {"error": "Invalid TOTP code"}, 400
        return {"status": "enabled"}, 200


@ns.route("/verify")
class TwoFAVerify(Resource):
    @jwt_required()
    @ns.expect(verify_in, validate=True)
    def post(self) -> Tuple[Dict[str, str], int]:
        """
        Проверяет TOTP-код при входе, если 2FA включена.

        Returns:
        JSON с результатом и HTTP статусом.

                 При успехе: {"status": "ok"}, 200
                 При ошибке:
                   - {"error": "2FA not enabled"}, 400 если 2FA не включена
                   - {"error": "Invalid TOTP code"}, 401 если код неверный
        """
        user = User.query.get_or_404(get_jwt_identity())
        code = request.json.get("code")
        if not user.is_2fa_enabled:
            return {"error": "2FA not enabled"}, 400
        if not TwoFAService.verify_login(user, code):
            return {"error": "Invalid TOTP code"}, 401
        return {"status": "ok"}, 200


@ns.route("/backup/generate")
class BackupGenerate(Resource):
    @jwt_required()
    def post(self) -> Tuple[Dict[str, Any], int]:
        """
        Генерирует и возвращает резервные коды для восстановления доступа к аккаунту.

        Returns:
        JSON с резервными кодами и HTTP статусом 200.

                 Формат:
                 {
                    "backup_codes": List[str]
                 }
        """
        user = User.query.get_or_404(get_jwt_identity())
        codes = TwoFAService.generate_backup_codes(user)
        return {"backup_codes": codes}, 200


@ns.route("/backup/use")
class BackupUse(Resource):
    @jwt_required()
    @ns.expect(backup_use_in, validate=True)
    def post(self) -> Tuple[Dict[str, str], int]:
        """
        Использует резервный код для входа при включенной 2FA.

        Returns:
        JSON с результатом и HTTP статусом.

                 При успехе: {"status": "ok"}, 200
                 При ошибке:
                   - {"error": "2FA not enabled"}, 400 если 2FA не включена
                   - {"error": "Invalid backup code"}, 401 если код неверный
        """
        user = User.query.get_or_404(get_jwt_identity())
        if not user.is_2fa_enabled:
            return {"error": "2FA not enabled"}, 400
        code = request.json.get("backup_code")
        if not TwoFAService.use_backup_code(user, code):
            return {"error": "Invalid backup code"}, 401
        return {"status": "ok"}, 200


@ns.route("/disable")
class TwoFADisable(Resource):
    @jwt_required()
    @ns.expect(disable_in, validate=True)
    def post(self) -> Tuple[Dict[str, str], int]:
        """
        Безопасно отключает двухфакторную аутентификацию Google Authenticator.

        Требует:
        - текущий пароль пользователя,
        - и один из кодов: действующий TOTP-код или резервный код.

        При успешном отключении удаляет секрет и резервные коды.

        Returns:
        JSON с результатом и HTTP статусом.

                 При успехе: {"status": "disabled_and_removed"}, 200
                 При ошибке: {"error": "Invalid credentials or code"}, 401
        """
        user = User.query.get_or_404(get_jwt_identity())
        data = request.get_json(force=True) or {}
        ok = TwoFAService.disable_secure(
            user,
            password=data.get("password", ""),
            code=data.get("code"),
            backup_code=data.get("backup_code"),
        )
        if not ok:
            return {"error": "Invalid credentials or code"}, 401
        return {"status": "disabled_and_removed"}, 200
