from flask import g
from onfine.models.user import User
from onfine.database import db


class UserService:

    @staticmethod
    def get_user_data(user_id):
        # Получаем данные пользователя по ID
        user = User.query.filter_by(id=user_id).first()
        if user is None:
            raise ValueError("User not found.")
        return user
