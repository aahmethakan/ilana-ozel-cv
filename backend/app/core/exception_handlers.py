from fastapi import Request
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
