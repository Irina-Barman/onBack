from typing import Any, Dict, Optional, Tuple

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services.auth_service import AuthService

from ..api.error_handlers import (
    EmailConfirmationError,
    PasswordResetError,
    RegistrationError,
    register_error_handlers,
)
from ..api.validators import validate_email, validate_password

auth_ns = Namespace(
    "auth",
    description="Регистрация • логин • восстановление пароля",
)

register_error_handlers(auth_ns)

# ----------- Swagger-модели ----------
# Модель ошибки
err_model = auth_ns.model(
    "Error",
    {
        "error": fields.String(description="Error code"),
        "message": fields.String(description="Error message"),
    },
)

register_in = auth_ns.model(
    "RegisterIn",
    {
        "email": fields.String(required=True, example="user@example.com"),
        "password": fields.String(required=True, example="secret"),
        "partner_uid": fields.String(required=False, example="111e2222-…"),
    },
)
register_out = auth_ns.model(
    "RegisterOut",
    {
        "message": fields.String,
        "user_id": fields.Integer,
    },
)

confirm_in = auth_ns.model(
    "ConfirmEmailIn",
    {"token": fields.String(required=True)},
)
login_in = auth_ns.model(
    "LoginIn",
    {"email": fields.String, "password": fields.String},
)
login_out = auth_ns.model(
    "LoginOut",
    {
        "accessToken": fields.String,
        "tokenType": fields.String,
        "expireTimestamp": fields.Integer,
    },
)
forgot_in = auth_ns.model("ForgotIn", {"email": fields.String})
reset_in = auth_ns.model(
    "ResetIn",
    {
        "token": fields.String,
        "newPassword": fields.String,
    },
)
msg_out = auth_ns.model("Message", {"message": fields.String})
user_out = auth_ns.model(
    "UserOut",
    {
        "email": fields.String,
        "isEmailConfirmed": fields.Boolean,
        "user_uid": fields.String,
    },
)


# ----------- /register ----------
@auth_ns.route("/register")
class Register(Resource):
    @auth_ns.expect(register_in)
    @auth_ns.marshal_with(register_out, code=200)
    @auth_ns.response(400, "Validation error", err_model)
    def post(self) -> Tuple[Dict[str, Any], int]:
        """
        Регистрация нового пользователя.

        Ожидает JSON-данные с полями 'email', 'password' и необязательным
        'partner_uid'. Если регистрация успешна, Return сообщение об
        успехе и идентификатор пользователя.

        Return:
            Tuple[Dict[str, Any], int]: Сообщение об успешной регистрации и
            идентификатор пользователя или ошибку валидации.
        """
        data: Dict[str, Any] = request.json or {}
        email: Optional[str] = data.get("email")
        password: Optional[str] = data.get("password")
        partner_uid: Optional[str] = data.get(
            "partner_uid"
        ) or request.args.get(
            "partner_uid",
        )

        try:
            validate_email(email)
            validate_password(password)
            user = AuthService.register_user(
                email=email,
                password=password,
                partner_uid=partner_uid,
            )
            return {
                "message": "Registration successful. Please confirm your e-mail.",
                "user_id": user.id,
            }, 200
        except ValueError as e:
            raise RegistrationError(str(e))


# ----------- /confirm-email ----------
@auth_ns.route("/confirm-email")
class ConfirmEmail(Resource):
    @auth_ns.expect(confirm_in)
    @auth_ns.marshal_with(msg_out)
    @auth_ns.response(400, "Bad token", err_model)
    def post(self) -> Dict[str, Any]:
        """
        Подтверждение email-адреса пользователя.

        Ожидает JSON-данные с полем 'token', который используется для
        подтверждения email-адреса. Если токен действителен, возвращает
        сообщение об успешном подтверждении.
        """
        data: Dict[str, Any] = request.json or {}
        token: Optional[str] = data.get("token")
        if not token:
            raise EmailConfirmationError("Token is required.")
        try:
            AuthService.confirm_email(token)
            return {"message": "Email confirmed."}
        except ValueError as e:
            raise EmailConfirmationError(str(e))


# ----------- /login ----------
@auth_ns.route("/login")
class Login(Resource):
    @auth_ns.expect(login_in)
    @auth_ns.marshal_with(login_out)
    @auth_ns.response(400, "Invalid creds / email not confirmed", err_model)
    def post(self) -> Dict[str, Any]:
        """
        Логин пользователя.

        Ожидает JSON-данные с полями 'email' и 'password'. Если
        учетные данные верны и email подтвержден, Return данные
        пользователя и токен доступа.

        Return:
            Dict[str, Any]: Данные пользователя и токен доступа или
            сообщение об ошибке при неверных учетных данных.
        """
        data: Dict[str, Any] = request.json
        return AuthService.login_user(data["email"], data["password"])


# ----------- /forgot-password ----------
@auth_ns.route("/forgot-password")
class ForgotPassword(Resource):
    @auth_ns.expect(forgot_in)
    @auth_ns.marshal_with(msg_out)
    @auth_ns.response(400, "Email not found", err_model)
    def post(self) -> Dict[str, Any]:
        """
        Запрос на восстановление пароля.

        Ожидает JSON-данные с полем 'email'. Если указанный email
        существует в системе, отправляет письмо для сброса пароля.

        Return:
            Dict[str, Any]: Сообщение об успешной отправке письма
            или сообщение об ошибке, если email не найден.
        """
        data: Dict[str, Any] = request.json
        AuthService.forgot_password(data["email"])
        return {"message": "Reset e-mail sent."}


# ----------- /reset-password ----------
@auth_ns.route("/reset-password")
class ResetPassword(Resource):
    @auth_ns.expect(reset_in)
    @auth_ns.marshal_with(msg_out)
    @auth_ns.response(400, "Bad token", err_model)
    def post(self) -> Dict[str, Any]:
        """
        Сброс пароля пользователя.

        Ожидает JSON-данные с полями 'token' и 'newPassword'.
        Если токен действителен, обновляет пароль пользователя.

        Return:
            Dict[str, Any]: Сообщение об успешном сбросе пароля или
            сообщение об ошибке при неверном токене.
        """
        data: Dict[str, Any] = request.json
        try:
            validate_password(data["newPassword"])
            return AuthService.reset_password(
                data["token"],
                data["newPassword"],
            )
        except ValueError as e:
            raise PasswordResetError(str(e))


# ----------- /logout ----------
@auth_ns.route("/logout")
class Logout(Resource):
    @auth_ns.marshal_with(msg_out)
    def post(self) -> Dict[str, Any]:
        """
        Выход пользователя.

        Проверяет наличие токена в заголовках запроса.
        Если токен отсутствует, Return сообщение об ошибке.
        Если токен присутствует, Return сообщение об успешном выходе.

        Return:
            Dict[str, Any]: Сообщение об успешном выходе или
            сообщение об ошибке, если токен отсутствует.
        """
        if not request.headers.get("Authorization"):
            return {"error": "Token is missing."}, 400
        return {"message": "Successfully logged out."}


# ----------- /user ----------
@auth_ns.route("/user")
class UserMe(Resource):
    @jwt_required()
    @auth_ns.marshal_with(user_out)
    def get(self) -> Dict[str, Any]:
        """
        Получение информации о текущем пользователе.

        Проверяет наличие валидного JWT токена и Return информацию о
        пользователе, включая email, статус подтверждения email и
        уникальный идентификатор пользователя.

        Return:
            Dict[str, Any]: Информацию о пользователе, включая:
                - email: Email пользователя
                - isEmailConfirmed: Статус подтверждения email
                - user_uid: Уникальный идентификатор пользователя
        """
        user = User.query.get(get_jwt_identity())
        return {
            "email": user.email,
            "isEmailConfirmed": user.email_confirmed,
            "user_uid": user.uid,
        }
