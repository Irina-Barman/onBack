from functools import wraps
from typing import Any, Callable, Dict, Tuple

import jwt
from flask import current_app, g, request
from flask_restx import Namespace, Resource, fields

user_ns = Namespace("User", description="User-related operations")

# Модель ответа для Swagger
user_model = user_ns.model(
    "User",
    {
        "email": fields.String,
        "isEmailConfirmed": fields.Boolean(attribute="is_email_confirmed"),
    },
)


def token_required(f: Callable[..., Any]) -> Callable[..., Tuple[dict, int]]:
    """Декоратор для проверки JWT токена в заголовках запроса.

    Этот декоратор проверяет наличие и действительность JWT токена
    в заголовках запроса.
    Если токен отсутствует или недействителен, Return ошибку.

    Аргументы:
        f: Функция, которую нужно декорировать.

    Return:
        Функция, которая Return словарь с ошибкой и статус-кодом,
        если токен недействителен,
        или вызывает оригинальную функцию, если токен действителен.
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Tuple[dict, int]:
        token = None
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]

        if not token:
            return {"error": "Token is missing."}, 403

        try:
            data = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=["HS256"],
            )
            g.user_id = data["user_id"]
        except Exception:
            return {"error": "Token is invalid or expired."}, 403

        return f(*args, **kwargs)

    return decorated_function


@user_ns.route("/info")
class UserResource(Resource):
    method_decorators = [
        token_required,
    ]  # применяем декоратор ко всем методам класса

    @user_ns.marshal_with(user_model)
    def get(self) -> Tuple[Dict[str, Any], int]:
        """
        Return данные пользователя, если токен действителен.
        """
        try:
            # user = UserService.get_user_data(g.user_id)
            # return user, 200
            user = {
                "message": "Успешно получены данные пользователя",
                "user_id": g.user_id,
            }
            return user, 200
        except ValueError as e:
            return {"error": str(e)}, 400
        except Exception as e:
            return {
                "error": f"An error occurred while fetching user data. \n{e}",
            }, 500
