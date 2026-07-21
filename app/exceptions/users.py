from app.exceptions.base import NotFoundError


class UserNotFoundError(NotFoundError):
    detail = "User not found"
