from flask import g, request, current_app
from flask_restx import Namespace, Resource, fields
from functools import wraps
import jwt

from onfine.services.user_service import UserService

user_ns = Namespace("User", description="User-related operations")

# Модель ответа для Swagger
user_model = user_ns.model("User", {
    "email": fields.String,
    "nickname": fields.String,
    "isEmailConfirmed": fields.Boolean(attribute="is_email_confirmed"),
})


def token_required(f):
    """Декоратор проверки JWT"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]

        if not token:
            return {"error": "Token is missing."}, 403

        try:
            data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
            g.user_id = data["user_id"]
        except Exception as e:
            return {"error": "Token is invalid or expired."}, 403

        return f(*args, **kwargs)
    return decorated_function


@user_ns.route("/info")
class UserResource(Resource):
    # method_decorators = [token_required]  # применяем декоратор ко всем методам класса
    # @user_ns.
    @user_ns.marshal_with(user_model)
    def get(self):
        """Получить данные пользователя по токену"""
        try:
            # user = UserService.get_user_data(g.user_id)
            # return user, 200
            return "ETO JOPA", 200
        except ValueError as e:
            return {"error": str(e)}, 400
        except Exception as e:
            return {"error": f"An error occurred while fetching user data. \n{e}"}, 500
