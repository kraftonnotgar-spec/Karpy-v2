import unittest
from types import SimpleNamespace

from .account_timezone import COUNTRY_TIMEZONES, account_timezone, country_timezone


def user(country=None, phone=None):
    meta = [SimpleNamespace(key="account.country_code", value=country)] if country else []
    return SimpleNamespace(meta=meta, phone=phone)


class AccountTimezoneTests(unittest.TestCase):
    def test_country_decides_the_zone(self):
        self.assertEqual(country_timezone("TZ"), "Africa/Dar_es_Salaam")
        self.assertEqual(country_timezone("ke"), "Africa/Nairobi")
        self.assertEqual(country_timezone("CD"), "Africa/Kinshasa")
        self.assertIsNone(country_timezone("US"))
        self.assertIsNone(country_timezone(None))
        self.assertEqual(len(COUNTRY_TIMEZONES), 13)

    def test_assigned_country_then_phone_country_then_unknown(self):
        self.assertEqual(account_timezone(user("TZ")), "Africa/Dar_es_Salaam")
        # The assignment wins over the phone's country.
        self.assertEqual(account_timezone(user("UG", "+255684104712")), "Africa/Kampala")
        self.assertEqual(account_timezone(user(phone="+255684104712")), "Africa/Dar_es_Salaam")
        self.assertEqual(account_timezone(user(phone="+254712345678")), "Africa/Nairobi")
        self.assertEqual(account_timezone(user("*", "+256712345678")), "Africa/Kampala")
        self.assertIsNone(account_timezone(user()))
        self.assertIsNone(account_timezone(user(phone="not a phone")))
        self.assertIsNone(account_timezone(user(phone="+14155552671")))


class AdminStatusTimezoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_merchant_profile_exposes_assigned_country_and_timezone(self):
        from unittest.mock import patch
        from . import routes
        with patch.object(routes, "user_payload", return_value={"id": "merchant-1"}):
            result = await routes.me(user("TZ", "+254712345678"))
        self.assertEqual(result["user"]["country"], "TZ")
        self.assertEqual(result["user"]["timezone"], "Africa/Dar_es_Salaam")

    async def test_admin_status_carries_the_account_timezone(self):
        from unittest.mock import AsyncMock, patch
        from karpy_platform.core.acl import routes

        admin = user("TZ")
        with patch.object(routes, "ensure_admin_user", AsyncMock()),                 patch.object(routes, "current_admin_user", AsyncMock(return_value=admin)),                 patch.object(routes, "user_payload", return_value={"id": "admin-1"}),                 patch.object(routes, "console_permissions", return_value=[]):
            result = await routes.auth_status(None, None)
        self.assertEqual(result["user"]["timezone"], "Africa/Dar_es_Salaam")


if __name__ == "__main__":
    unittest.main()
