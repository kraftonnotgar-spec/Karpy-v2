from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import JSONResponse

from karpy_platform.core.base.helpers import clean


@dataclass
class BaseHttpResponse:
    """Small Python version of Botble's chainable BaseHttpResponse."""

    error: bool = False
    data: Any = None
    message: str | None = None
    previous_url: str = ""
    next_url: str = ""
    code: int = 200
    additional: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def make(cls) -> "BaseHttpResponse":
        return cls()

    def set_data(self, data: Any) -> "BaseHttpResponse":
        self.data = data
        return self

    def set_message(self, message: str | None, clean_html_tags: bool = True) -> "BaseHttpResponse":
        self.message = clean(message) if clean_html_tags else message
        return self

    def set_error(self, error: bool = True) -> "BaseHttpResponse":
        self.error = error
        return self

    def set_code(self, code: int) -> "BaseHttpResponse":
        if 100 <= code < 600:
            self.code = code
        return self

    def set_previous_url(self, url: str) -> "BaseHttpResponse":
        self.previous_url = url
        return self

    def set_next_url(self, url: str) -> "BaseHttpResponse":
        self.next_url = url
        return self

    def set_additional(self, additional: dict[str, Any]) -> "BaseHttpResponse":
        self.additional = additional
        return self

    def with_created_success_message(self) -> "BaseHttpResponse":
        return self.set_message("Created successfully")

    def with_updated_success_message(self) -> "BaseHttpResponse":
        return self.set_message("Updated successfully")

    def with_deleted_success_message(self) -> "BaseHttpResponse":
        return self.set_message("Deleted successfully")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "error": self.error,
            "data": self.data,
            "message": self.message,
        }
        if self.previous_url:
            payload["previous_url"] = self.previous_url
        if self.next_url:
            payload["next_url"] = self.next_url
        if self.additional:
            payload["additional"] = self.additional
        return payload

    def to_response(self) -> JSONResponse:
        return JSONResponse(self.to_dict(), status_code=self.code)
