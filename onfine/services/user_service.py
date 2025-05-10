from onfine.models.user import User


class UserService:

    @staticmethod
    def get_user_data(user_id: int) -> User:
        """
        Получает данные пользователя по ID.
        Returns:
            User: Объект пользователя, если найден, иначе вызывает ValueError.

        Raises:
            ValueError: Если пользователь с указанным ID не найден.
        """
        user = User.query.filter_by(id=user_id).first()
        if user is None:
            raise ValueError("User not found.")
        return user
