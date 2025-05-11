import re
from typing import Any, Dict, Tuple

from flask import request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_restx import Namespace, Resource, fields

from onfine.models.user import User
from onfine.services.auth_service import AuthService

auth_ns = Namespace(
    "auth", description="Регистрация • логин • восстановление пароля"
)

# ----------- Swagger-модели ----------
err_model = auth_ns.model("Error", {"error": fields.String})

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
        data = request.json or {}
        partner_uid = data.get("partner_uid") or request.args.get(
            "partner_uid"
        )

        # Проверка корректности email
        if not self.is_valid_email(data.get("email", "")):
            return {"error": "Некорректный email."}, 400

        # Проверка сложности пароля
        password_check = self.is_strong_password(data.get("password", ""))
        if password_check is not True:
            return {"error": password_check}, 400

        # Проверка на существование пользователя с таким email
        if AuthService.user_exists(data["email"]):
            return {
                "error": "Пользователь с таким email уже зарегистрирован."
            }, 400

        try:
            user = AuthService.register_user(
                email=data["email"],
                password=data["password"],
                partner_uid=partner_uid,
            )
            return {
                "message": "Регистрация успешна. Пожалуйста, подтвердите ваш email.",
                "user_id": user.id,
            }, 200
        except ValueError as e:
            return {"error": str(e)}, 400

    def is_valid_email(self, email: str) -> bool:
        """
        Проверка корректности email.
        """
        email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(email_regex, email) is not None

    def is_strong_password(self, password: str) -> Any:
        """
        Проверка сложности пароля.
        Возвращает True, если пароль сильный, или сообщение об ошибке, если нет.
        """
        if len(password) < 8:
            return "Пароль должен содержать минимум 8 символов."
        if not any(c.isdigit() for c in password):
            return "Пароль должен содержать хотя бы одну цифру."
        if not any(c.isalpha() for c in password):
            return "Пароль должен содержать хотя бы одну букву."
        return True


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
        подтверждения email-адреса. Если токен действителен, Return
        сообщение об успешном подтверждении.

        Return:
            Dict[str, Any]: Сообщение об успешном подтверждении email
            или ошибку валидации.
        """
        data = request.json
        try:
            AuthService.confirm_email(data["token"])
            return {"message": "Email confirmed."}
        except ValueError as e:
            return {"error": str(e)}, 400


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
        data = request.json
        try:
            return AuthService.login_user(data["email"], data["password"])
        except ValueError as e:
            return {"error": str(e)}, 400


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
        data = request.json
        try:
            AuthService.forgot_password(data["email"])
            return {"message": "Reset e-mail sent."}
        except ValueError as e:
            return {"error": str(e)}, 400


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
        data = request.json
        try:
            return AuthService.reset_password(
                data["token"],
                data["newPassword"],
            )
        except ValueError as e:
            return {"error": str(e)}, 400


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
