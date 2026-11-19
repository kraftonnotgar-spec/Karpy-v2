from __future__ import annotations

from typing import Any, Protocol

from fastapi import Request


class ProduceServiceInterface(Protocol):
    async def execute(self, request: Request) -> Any:
        ...


class SupportServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        self._services[name] = service

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def has(self, name: str) -> bool:
        return name in self._services

    def all(self) -> dict[str, Any]:
        return dict(self._services)


support_services = SupportServiceRegistry()
