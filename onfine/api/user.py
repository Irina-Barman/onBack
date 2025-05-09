from flask import g, request, current_app
from flask_restx import Namespace, Resource, fields
from functools import wraps
import jwt
import logging
from typing import Any, Dict, Tuple


from onfine.services.user_service import UserService

user_ns = Namespace("User", description="Операции, связанные с пользователем")

# Модель ответа для Swagger
user_model = user_ns.model(
    "User",
    {
        "email": fields.String,
        "isEmailConfirmed": fields.Boolean(attribute="is_email_confirmed"),
    },
)


def token_required(f) -> Any:
    """Декоратор для проверки наличия и валидности JWT токена.

    Проверяет, есть ли JWT токен в заголовках запроса. Если токен отсутствует
    или недействителен, возвращает ошибку 403.

    Args:
        f: Декорируемая функция.

    Returns:
        Декорированная функция с проверкой токена.
    """

    @wraps(f)
    def decorated_function(
        *args: Any, **kwargs: Any
    ) -> Tuple[Dict[str, str], int]:
        token = None
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]

        if not token:
            logging.warning("Попытка доступа без токена.")
            return {"error": "Token is missing."}, 403

        try:
            data = jwt.decode(
                token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
            )
            g.user_id = data["user_id"]
        except jwt.ExpiredSignatureError:
            logging.warning("Токен истек.")
            return {"error": "Token is expired."}, 403
        except jwt.InvalidTokenError:
            logging.warning("Недействительный токен.")
            return {"error": "Token is invalid."}, 403

        return f(*args, **kwargs)

    return decorated_function


@user_ns.route("/info")
class UserResource(Resource):
    method_decorators = [token_required]

    @user_ns.marshal_with(user_model)
    def get(self):
        """Получить данные пользователя по токену"""
        try:
            user = UserService.get_user_data(g.user_id)
            if not user:
                logging.info(f"Пользователь с ID {g.user_id} не найден.")
                return {"error": "User not found."}, 404
            return user, 200
        except ValueError as e:
            logging.error(f"Ошибка значения: {str(e)}")
            return {"error": str(e)}, 400
        except Exception as e:
            logging.error(
                f"Произошла ошибка при получении данных пользователя: {str(e)}"
            )
            return {
                "error": "An error occurred while fetching user data."
            }, 500
