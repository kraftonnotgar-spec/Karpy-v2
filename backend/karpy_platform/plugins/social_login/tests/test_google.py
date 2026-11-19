from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from karpy_platform.plugins.social_login.services.google import (
    GoogleConfiguration,
    SocialLoginError,
    _pkce_challenge,
    safe_return_to,
    verify_google_identity,
)


class GoogleLoginSecurityTests(unittest.TestCase):
    def test_configuration_requires_global_provider_and_credentials(self) -> None:
        base = {
            "globally_enabled": True,
            "enabled": True,
            "client_id": "client-id",
            "client_secret": "client-secret",
            "allow_registration": False,
            "style": "basic",
            "callback_url": "https://cms.example.com/api/plugins/social_login/google/callback",
        }
        self.assertTrue(GoogleConfiguration(**base).configured)
        self.assertFalse(
            GoogleConfiguration(**{**base, "client_secret": ""}).configured
        )
        self.assertFalse(
            GoogleConfiguration(**{**base, "globally_enabled": False}).configured
        )

    def test_return_url_accepts_only_the_current_origin(self) -> None:
        origin = "https://cms.example.com"
        self.assertEqual(
            safe_return_to("/admin", origin), "https://cms.example.com/admin"
        )
        self.assertEqual(
            safe_return_to("https://cms.example.com/admin/pages", origin),
            "https://cms.example.com/admin/pages",
        )
        self.assertEqual(
            safe_return_to("https://evil.example/admin", origin),
            "https://cms.example.com/admin",
        )
        self.assertEqual(
            safe_return_to("https://cms.example.com:444/admin", origin),
            "https://cms.example.com/admin",
        )
        self.assertEqual(
            safe_return_to("//evil.example/admin", origin),
            "https://cms.example.com/admin",
        )

    def test_pkce_challenge_is_deterministic_and_url_safe(self) -> None:
        verifier = "a-secure-verifier-value-with-enough-entropy"
        challenge = _pkce_challenge(verifier)
        self.assertEqual(challenge, _pkce_challenge(verifier))
        self.assertNotIn("=", challenge)
        self.assertNotIn("+", challenge)
        self.assertNotIn("/", challenge)


class GoogleIdentityJWTTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self.jwk = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        self.jwk["kid"] = "google-active"
        self.config = GoogleConfiguration(
            True,
            True,
            "client-id",
            "client-secret",
            False,
            "basic",
            "https://api.example/callback",
        )

    def token(self, **overrides) -> str:
        payload = {
            "sub": "google-user",
            "email": "user@example.com",
            "email_verified": True,
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "nonce": "expected-nonce",
        }
        payload.update(overrides)
        return jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
            headers={"kid": "google-active"},
        )

    async def test_cryptography_backed_rs256_identity_verification(self) -> None:
        with patch(
            "karpy_platform.plugins.social_login.services.google._google_jwks",
            AsyncMock(return_value={"keys": [self.jwk]}),
        ):
            claims = await verify_google_identity(
                self.token(), self.config, "expected-nonce"
            )
        self.assertEqual(claims["sub"], "google-user")

    async def test_wrong_audience_nonce_and_tamper_are_rejected(self) -> None:
        tokens = [
            (self.token(aud="wrong-client"), "expected-nonce"),
            (self.token(), "wrong-nonce"),
        ]
        valid = self.token()
        # Mutate significant signature bits. The final Base64url character has
        # unused padding bits and can change without changing decoded bytes.
        header, payload, signature = valid.split(".")
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        tokens.append((f"{header}.{payload}.{signature}", "expected-nonce"))
        with patch(
            "karpy_platform.plugins.social_login.services.google._google_jwks",
            AsyncMock(return_value={"keys": [self.jwk]}),
        ):
            for token, nonce in tokens:
                with self.assertRaises(SocialLoginError):
                    await verify_google_identity(token, self.config, nonce)


if __name__ == "__main__":
    unittest.main()
