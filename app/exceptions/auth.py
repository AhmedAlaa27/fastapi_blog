from app.exceptions.base import PermissionDeniedError, UnauthorizedError


class InvalidCredentialsError(UnauthorizedError):
    detail = "Incorrect email or password"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class InvalidTokenError(UnauthorizedError):
    detail = "Invalid or expired token"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class EmailNotVerifiedError(PermissionDeniedError):
    detail = "Please verify your email before logging in."
