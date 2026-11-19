"""Payment imports/secret compatibility and optional capability regressions."""

import asyncio
import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.config import settings
from karpy_platform.core.security.secrets import decrypt_secret, encrypt_secret
from karpy_platform.plugins.payment.services.checkout import (
    complete_payment,
    create_plan_checkout,
)
from karpy_platform.plugins.payment.services.fulfilment import (
    FulfilmentExtension,
    FulfilmentRegistry,
    fulfilment_extensions,
)


def payment(payment_type="generic"):
    return SimpleNamespace(
        status="pending",
        payment_type=payment_type,
        user_id="test-user",
        payment_metadata={},
    )


def test_existing_ciphertext_and_plaintext_compatibility():
    with patch.object(settings, "SECRET_KEY", "test-only-encryption-key"):
        legacy = (
            "enc:v1:"
            + Fernet(
                base64.urlsafe_b64encode(
                    hashlib.sha256(settings.SECRET_KEY.encode()).digest()
                )
            )
            .encrypt(b"existing-setting")
            .decode()
        )
        assert decrypt_secret(legacy) == "existing-setting"
        assert decrypt_secret(encrypt_secret("new-setting")) == "new-setting"
        assert decrypt_secret("legacy-plaintext") == "legacy-plaintext"
        for value in (None, "", "enc:v1:broken", "enc:v1:\u2603", "enc:v2:unknown"):
            assert decrypt_secret(value) == ""
        with patch.object(settings, "SECRET_KEY", "different-test-only-key"):
            assert decrypt_secret(legacy) == ""


def test_generic_payment_completes_without_product_plugin():
    db = AsyncMock()
    result = asyncio.run(
        complete_payment(db, payment(), "completed", event_id="test-event")
    )
    assert result.status == "completed"
    assert "fulfilment" not in result.payment_metadata
    db.commit.assert_awaited_once()


def test_missing_product_capability_is_controlled_before_any_database_write():
    db = AsyncMock()
    with pytest.raises(HTTPException) as failure:
        asyncio.run(create_plan_checkout(db, None, None, "product", "method"))
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "capability_unavailable"
    assert db.mock_calls == []
    result = asyncio.run(complete_payment(db, payment("plan"), "completed"))
    assert result.status == "completed"
    assert result.payment_metadata["fulfilment"]["status"] == "unavailable"


def test_optional_extension_owns_checkout_and_cancellation():
    db = AsyncMock()
    checkout, transition = AsyncMock(return_value={"status": "pending"}), AsyncMock()
    fulfilment_extensions.register(
        "plan", FulfilmentExtension("test_product", checkout, transition)
    )
    try:
        assert asyncio.run(
            create_plan_checkout(db, None, None, "product", "method")
        ) == {"status": "pending"}
        item = payment("plan")
        asyncio.run(complete_payment(db, item, "refunded", actor_id="operator"))
        checkout.assert_awaited_once_with(db, None, None, "product", "method")
        transition.assert_awaited_once_with(db, item, "refunded", "operator")
    finally:
        fulfilment_extensions.unregister("plan", owner="test_product")


def test_extension_failure_rolls_back_and_returns_safe_error():
    db = AsyncMock()
    extension = FulfilmentExtension(
        "test_product",
        AsyncMock(),
        AsyncMock(side_effect=RuntimeError("sensitive plugin detail")),
    )
    fulfilment_extensions.register("plan", extension)
    try:
        with pytest.raises(HTTPException) as failure:
            asyncio.run(complete_payment(db, payment("plan"), "completed"))
        assert failure.value.status_code == 503
        assert "sensitive" not in str(failure.value.detail)
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
    finally:
        fulfilment_extensions.unregister("plan", owner="test_product")


def test_extension_registration_is_exclusive_and_owner_scoped():
    registry = FulfilmentRegistry()
    extension = FulfilmentExtension("test_product", AsyncMock(), AsyncMock())
    registry.register("product", extension)
    with pytest.raises(ValueError):
        registry.register("product", extension)
    with pytest.raises(ValueError):
        registry.unregister("product", owner="another_plugin")
    assert registry.get("product") is extension
    registry.unregister("product", owner="test_product")
    assert registry.get("product") is None
