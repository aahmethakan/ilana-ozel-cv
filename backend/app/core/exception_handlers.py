from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ErrorDetail, ErrorResponse


async def unexpected_exception_handler(_: Request, __: Exception) -> JSONResponse:
    error_response = ErrorResponse(
        error=ErrorDetail(
            code="internal_server_error",
            message="An unexpected error occurred.",
        )
    )
    return JSONResponse(status_code=500, content=error_response.model_dump())


def _error_response(*, code: str, message: str, status_code: int) -> JSONResponse:
    """Return the one public error envelope used by the HTTP API.

    FastAPI's default validation payload can include implementation-specific
    locations and Pydantic messages.  Those details are useful in server logs,
    but they are neither a stable client contract nor safe public output.
    """
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump(),
    )


async def api_http_exception_handler(_: Request, error: HTTPException) -> JSONResponse:
    detail = error.detail
    if isinstance(detail, dict) and isinstance(detail.get("code"), str) and isinstance(detail.get("message"), str):
        return _error_response(code=detail["code"], message=detail["message"], status_code=error.status_code)
    return _error_response(
        code="request_failed",
        message="The request could not be completed.",
        status_code=error.status_code,
    )


async def request_validation_exception_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return _error_response(
        code="invalid_request",
        message="The request data is invalid.",
        status_code=422,
    )
