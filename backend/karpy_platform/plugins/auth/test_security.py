from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException

from app.config import settings
from karpy_platform.plugins.auth.security import decode_access_token, issue_access_token


class AccessTokenRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patchers = [
            patch.object(settings, "JWT_SECRET", "test-jwt-secret-that-is-at-least-32-bytes"),
            patch.object(settings, "JWT_ALGORITHM", "HS256"),
            patch.object(settings, "APP_URL", "https://api.example.test"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_issued_token_preserves_subject_session_issuer_and_expiry(self) -> None:
        payload = decode_access_token(issue_access_token("user-1", "session-1"))
        self.assertEqual(payload["sub"], "user-1")
        self.assertEqual(payload["sid"], "session-1")
        self.assertEqual(payload["iss"], "https://api.example.test")
        self.assertEqual(payload["type"], "access")

    def test_tampered_expired_and_wrong_issuer_tokens_are_rejected(self) -> None:
        good = issue_access_token("user-1", "session-1")
        header, payload, signature = good.split(".")
        tampered = ".".join((header, payload, ("a" if signature[0] != "a" else "b") + signature[1:]))
        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {"sub": "user-1", "sid": "session-1", "type": "access", "iss": settings.APP_URL, "exp": now - timedelta(seconds=1)},
            settings.JWT_SECRET,
            algorithm="HS256",
        )
        wrong_issuer = jwt.encode(
            {"sub": "user-1", "sid": "session-1", "type": "access", "iss": "https://evil.example", "exp": now + timedelta(minutes=5)},
            settings.JWT_SECRET,
            algorithm="HS256",
        )
        for token in (tampered, expired, wrong_issuer):
            with self.assertRaises(HTTPException) as raised:
                decode_access_token(token)
            self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
