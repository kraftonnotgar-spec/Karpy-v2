"""Provider events may only move a payment forward."""
from __future__ import annotations

import unittest

from karpy_platform.plugins.payment.services.checkout import provider_transition_allowed


class ProviderTransitionTests(unittest.TestCase):
    def test_pending_payments_can_settle_or_fail(self):
        for status in ("processing", "completed", "failed", "canceled"):
            self.assertTrue(provider_transition_allowed("pending", status), status)

    def test_completed_payments_cannot_be_undone_by_late_events(self):
        for status in ("pending", "processing", "failed", "canceled"):
            self.assertFalse(provider_transition_allowed("completed", status), status)
        self.assertTrue(provider_transition_allowed("completed", "refunded"))

    def test_refunds_are_final_and_money_after_expiry_is_kept(self):
        self.assertFalse(provider_transition_allowed("refunded", "completed"))
        self.assertTrue(provider_transition_allowed("failed", "completed"))
        self.assertFalse(provider_transition_allowed("failed", "pending"))

    def test_unknown_statuses_are_rejected(self):
        self.assertFalse(provider_transition_allowed("pending", "paid_twice"))
        self.assertFalse(provider_transition_allowed("pending", ""))


if __name__ == "__main__":
    unittest.main()
