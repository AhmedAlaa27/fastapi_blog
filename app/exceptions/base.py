class AppException(Exception):
    status_code: int = 500
    detail: str = "Internal server error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.detail
        if status_code is not None:
            self.status_code = status_code
        self.headers = headers
        super().__init__(self.detail)


class NotFoundError(AppException):
    status_code = 404
    detail = "Not found"


class AlreadyExistsError(AppException):
    status_code = 400
    detail = "Already exists"


class PermissionDeniedError(AppException):
    status_code = 403
    detail = "Not enough permissions"


class UnauthorizedError(AppException):
    status_code = 401
    detail = "Not authenticated"


class BadRequestError(AppException):
    status_code = 400
    detail = "Bad request"
