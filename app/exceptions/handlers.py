from fastapi import Request
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.base import AppException


async def app_exception_handler(request: Request, exc: AppException) -> Response:
    http_exc = StarletteHTTPException(
        status_code=exc.status_code, detail=exc.detail, headers=exc.headers
    )
    handler = request.app.exception_handlers[StarletteHTTPException]
    return await handler(request, http_exc)
