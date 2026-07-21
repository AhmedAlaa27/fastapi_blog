from app.exceptions.base import NotFoundError


class PostNotFoundError(NotFoundError):
    detail = "Post not found"
