from functools import wraps
from typing import Any, Callable, Dict, Tuple

import jwt
from flask import current_app, g, request
from flask_restx import Namespace, Resource, fields

user_ns = Namespace("user", description="User-related operations")

# Модель ответа для Swagger
user_model = user_ns.model(
    "user",
    {
        "message": fields.String,
        "user_id": fields.String,
    },
)


def token_required(
    f: Callable[..., Any],
) -> Callable[..., Tuple[Dict[str, Any], int]]:
    """
    Декоратор для проверки JWT токена в заголовках запроса.

    Проверяет наличие и валидность JWT токена в заголовке Authorization.
    Если токен отсутствует или недействителен — возвращает ошибку с HTTP 403.
    Если токен валиден — сохраняет user_id в flask.g и вызывает декорируемую функцию.

    Args:
        f: Функция, которую декорируем.

    Returns:
        Обёртка, которая возвращает кортеж (словарь, HTTP статус).
    """

    @wraps(f)
    def decorated_function(
        *args: Any, **kwargs: Any
    ) -> Tuple[Dict[str, Any], int]:
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

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
    method_decorators = [token_required]

    @user_ns.marshal_with(user_model)
    def get(self) -> Tuple[Dict[str, Any], int]:
        """
        Возвращает данные пользователя по JWT токену.

        В GET-запросе тело (body) не используется, только query-параметры (request.args).

        Returns:
            Tuple[Dict[str, Any], int]: Словарь с данными пользователя и HTTP статус.
        """
        try:
            # Здесь можно получить дополнительные параметры из query, например:
            # param = request.args.get("param_name")

            user_data = {
                "message": "Успешно получены данные пользователя",
                "user_id": str(g.user_id),
            }
            return user_data, 200
        except ValueError as e:
            return {"error": str(e)}, 400
        except Exception as e:
            return {
                "error": f"An error occurred while fetching user data.\n{e}"
            }, 500
