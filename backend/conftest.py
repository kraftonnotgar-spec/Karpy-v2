"""Provider tests must never initiate external network connections."""
from __future__ import annotations

import ipaddress
import socket

import pytest


@pytest.fixture(autouse=True)
def loopback_network_only(monkeypatch):
    lookup, connect, connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex

    def allowed(host):
        try:
            host = host.decode("ascii") if isinstance(host, bytes) else host
            return host == "localhost" or ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False

    def checked_lookup(host, port, family=0, type=0, proto=0, flags=0):
        if not allowed(host):
            raise RuntimeError("External network disabled in tests; use a mock transport or loopback")
        if host in {"localhost", b"localhost"}:
            host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        return lookup(host, port, family, type, proto, flags)

    def checked_connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6} and not allowed(address[0]):
            raise RuntimeError("External network disabled in tests; use a mock transport or loopback")
        return connect(sock, address)

    def checked_connect_ex(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6} and not allowed(address[0]):
            raise RuntimeError("External network disabled in tests; use a mock transport or loopback")
        return connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", checked_lookup)
    monkeypatch.setattr(socket.socket, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_connect_ex)
