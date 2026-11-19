"""Manual payment method registration and checkout instructions."""

from typing import Any

from karpy_platform.plugins.payment.services.checkout import CheckoutContext
from karpy_platform.plugins.payment.services.gateway_fields import common_gateway_fields, country_availability_field
from karpy_platform.plugins.payment.services.methods import PaymentMethodField, checkout_handlers, payment_methods

KEY = "manual"


def register_gateway() -> None:
    payment_methods.register(
        KEY,
        name="Manual payment",
        description="Bank transfer, Binance Pay, wallet, or another administrator-approved method.",
        priority=30,
        source="manual_payment",
        checkout_type="manual",
        setup_instructions=[
            "Choose the provider customers should pay through.",
            "Enter the account, wallet, network, and exact payment instructions.",
            "Confirm each submitted reference from Payment Transactions before fulfilment.",
        ],
        fields=[
            *common_gateway_fields(),
            PaymentMethodField("methodLogo", "Method logo", type="media", help="Displayed beside this method during customer checkout."),
            PaymentMethodField("providerName", "Provider name", placeholder="Binance Pay"),
            PaymentMethodField("accountLabel", "Account label", placeholder="Binance Pay ID"),
            PaymentMethodField("accountValue", "Account / wallet", placeholder="Account, wallet, or payment ID"),
            PaymentMethodField("network", "Network", placeholder="Optional, e.g. TRC20"),
            PaymentMethodField("instructions", "Payment instructions", placeholder="Explain how to pay and which reference to include"),
            country_availability_field(),
        ],
    )
    checkout_handlers.register(KEY, create_checkout)


def unregister_gateway() -> None:
    checkout_handlers.unregister(KEY)
    payment_methods.unregister(KEY)


async def create_checkout(context: CheckoutContext) -> dict[str, Any]:
    settings, payment = context.settings, context.payment
    return {
        "status": "pending",
        "message": "Payment request created. Complete the transfer and keep this reference.",
        "reference": payment.id,
        "manual": {
            "provider": settings.get("providerName") or settings.get("methodName") or "Manual payment",
            "accountLabel": settings.get("accountLabel") or "Payment account",
            "accountValue": settings.get("accountValue") or "",
            "network": settings.get("network") or "",
            "instructions": settings.get("instructions") or "Contact support with your payment reference.",
        },
    }
