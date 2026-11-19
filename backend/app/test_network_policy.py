import socket

import pytest


def test_external_dns_and_provider_connections_are_blocked():
    with pytest.raises(RuntimeError, match="External network disabled"):
        socket.getaddrinfo("provider.example.invalid", 443)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        with pytest.raises(RuntimeError, match="External network disabled"):
            connection.connect(("203.0.113.12", 443))
        with pytest.raises(RuntimeError, match="External network disabled"):
            connection.connect_ex(("203.0.113.12", 443))


def test_loopback_resolution_is_available_without_external_dns():
    addresses = socket.getaddrinfo("localhost", 443, socket.AF_INET, socket.SOCK_STREAM)
    assert addresses
    assert all(item[4][0] == "127.0.0.1" for item in addresses)
