"""Uniform JSON error responses."""
from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("iron.errors")


class ApiError(Exception):
    """Raise anywhere in a request to return a structured error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return JSONResponse(body, status_code=status_code, headers=headers)


def _friendly(err: dict) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    msg = str(err.get("msg", "Invalid value"))
    if kind == "missing":
        return "This field is required"
    if kind == "string_too_short":
        return "This field is required" if ctx.get("min_length") == 1 else f"Use at least {ctx.get('min_length')} characters"
    if kind == "string_too_long":
        return f"Use at most {ctx.get('max_length')} characters"
    if kind in ("literal_error", "enum"):
        return "Choose one of the available options"
    if kind in ("greater_than_equal", "less_than_equal", "greater_than", "less_than"):
        return "That number is out of range"
    if kind in ("too_short", "too_long"):
        return "Check the number of selected items"
    if kind in ("string_type", "int_parsing", "float_parsing", "bool_parsing", "int_type", "float_type"):
        return "Enter a valid value"
    if kind in ("json_invalid", "model_attributes_type", "dict_type"):
        return "Send a valid JSON body"
    msg = re.sub(r"^Value error, ", "", msg)
    lowered = msg.lower()
    if "valid email" in lowered or "email address" in lowered:
        return "Enter a valid email address"
    return msg


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message, fields=exc.fields, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            key = ".".join(loc) or "_"
            fields.setdefault(key, _friendly(err))
        return error_response(422, "validation_error", "Please check the highlighted fields.", fields=fields)
