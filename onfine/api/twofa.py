from io import BytesIO

from flask import request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services.twofa_service import TwoFAService

ns = Namespace("2fa", description="Two-Factor Authentication", path="/auth/2fa")

twofa_setup = ns.model(
    "TwoFASetup",
    {
        "otpauth_url": fields.String(required=True),
        "qr_data_url": fields.String(required=True),
    },
)

enable_in = ns.model(
    "TwoFAEnableIn",
    {
        "code": fields.String(required=True, min_length=6, max_length=6),
    },
)

verify_in = ns.model(
    "TwoFAVerifyIn",
    {
        "code": fields.String(required=True, min_length=6, max_length=6),
    },
)

backup_use_in = ns.model(
    "BackupUseIn",
    {
        "backup_code": fields.String(required=True),
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
    def post(self):  # noqa: D102, ANN201
        user = User.query.get_or_404(get_jwt_identity())
        return TwoFAService.provisioning(user), 200


@ns.route("/qr.png")
class TwoFAQr(Resource):
    @jwt_required()
    def get(self):  # noqa: D102, ANN201
        user = User.query.get_or_404(get_jwt_identity())
        raw = TwoFAService.provisioning_png(user)
        return send_file(BytesIO(raw), mimetype="image/png")


@ns.route("/enable")
class TwoFAEnable(Resource):
    @jwt_required()
    @ns.expect(enable_in, validate=True)
    def post(self):  # noqa: D102, ANN201
        user = User.query.get_or_404(get_jwt_identity())
        code = request.json.get("code")
        if not TwoFAService.enable(user, code):
            return {"error": "Invalid TOTP code"}, 400
        return {"status": "enabled"}, 200


@ns.route("/verify")
class TwoFAVerify(Resource):
    @jwt_required()
    @ns.expect(verify_in, validate=True)
    def post(self):  # noqa: D102, ANN201
        user = User.query.get_or_404(get_jwt_identity())
        code = request.json.get("code")
        if not user.is_2fa_enabled:
            return {"error": "2FA not enabled"}, 400
        if not TwoFAService.verify_login(user, code):
            return {"error": "Invalid TOTP code"}, 401
        # 2FA passed; your frontend can proceed or you can mark session as 2FA-verified here.
        return {"status": "ok"}, 200


@ns.route("/backup/generate")
class BackupGenerate(Resource):
    @jwt_required()
    def post(self):  # noqa: D102, ANN201
        user = User.query.get_or_404(get_jwt_identity())
        codes = TwoFAService.generate_backup_codes(user)
        return {"backup_codes": codes}, 200


@ns.route("/backup/use")
class BackupUse(Resource):
    @jwt_required()
    @ns.expect(backup_use_in, validate=True)
    def post(self):  # noqa: D102, ANN201
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
    def post(self):  # noqa: ANN201
        """
        Безопасно отключить Google Authenticator:
        - требует пароль + (TOTP-код ИЛИ резервный код)
        - выключает 2FA и стирает секрет/резервные коды
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
