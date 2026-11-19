from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles


class PublicMediaFiles(StaticFiles):
    """Never expose legacy upload scratch files through the public media mount."""

    async def get_response(self, path, scope):
        if any(part.startswith(".") for part in path.replace("\\", "/").split("/")):
            raise HTTPException(404)
        return await super().get_response(path, scope)


class RequestBodyTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    """Reject oversized HTTP bodies before form or upload parsing begins."""

    def __init__(self, app: Callable[..., Awaitable[None]], max_body_size: int) -> None:
        if max_body_size < 1:
            raise ValueError("max_body_size must be positive")
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                await self._reject(scope, receive, send, 400, "invalid_content_length")
                return
            if declared_size < 0:
                await self._reject(scope, receive, send, 400, "invalid_content_length")
                return
            if declared_size > self.max_body_size:
                await self._reject(scope, receive, send, 413, "request_body_too_large")
                return

        received_size = 0
        response_started = False

        async def limited_receive():
            nonlocal received_size
            message = await receive()
            if message.get("type") == "http.request":
                received_size += len(message.get("body", b""))
                if received_size > self.max_body_size:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send, 413, "request_body_too_large")

    @staticmethod
    async def _reject(scope, receive, send, status_code: int, code: str) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": "The request body is invalid or exceeds the configured limit.", "code": code},
        )
        await response(scope, receive, send)


def safe_upload_filename(filename: str | None, default: str = "file") -> str:
    """Return a basename consistently on Windows and POSIX hosts."""
    normalized = (filename or "").replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].replace("\x00", "").strip()
    return default if name in {"", ".", ".."} else name
