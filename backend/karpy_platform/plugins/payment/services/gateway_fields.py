"""Reusable Botble-style fields that gateway plugins may opt into."""

from .methods import PaymentMethodField


def common_gateway_fields() -> list[PaymentMethodField]:
    return [
        PaymentMethodField("methodName", "Method name", placeholder="Pay securely", help="Shown to customers during checkout."),
        PaymentMethodField("description", "Description", placeholder="Secure online payment"),
        PaymentMethodField("processingFee", "Processing fee (optional)", type="number", placeholder="0", help="Enter 0 for no additional fee."),
        PaymentMethodField(
            "processingFeeType",
            "Processing fee type (optional)",
            type="select",
            options=[{"label": "Fixed", "value": "fixed"}, {"label": "Percentage", "value": "percentage"}],
        ),
    ]


def country_availability_field() -> PaymentMethodField:
    """Keep country availability last in every Botble-style gateway form."""
    return PaymentMethodField(
        "countries",
        "Available countries",
        type="countries",
        help="Choose where this payment method is available.",
    )
