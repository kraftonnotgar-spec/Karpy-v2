"""Settings encryption compatible with existing enc:v1 Fernet values.

The key derivation and envelope are deliberately unchanged. Rotating SECRET_KEY
requires a separate settings re-encryption procedure; do not rotate it casually.
Unencrypted legacy settings remain readable, but all new writes are encrypted.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return "enc:v1:" + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    if not text.startswith("enc:"):
        return text
    if not text.startswith("enc:v1:"):
        return ""
    try:
        return (
            _fernet()
            .decrypt(text.removeprefix("enc:v1:").encode("ascii"))
            .decode("utf-8")
        )
    except (InvalidToken, UnicodeError, ValueError):
        return ""
