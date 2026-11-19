"""Display timezone for an account, from the account's country.

The platform does not store a per-account timezone. Settings > Profile used to show the
browser's zone, and Windows reports every UTC+3 East African zone as Africa/Nairobi,
so Tanzanian accounts saw "Africa/Nairobi". The zone now follows the account country:
the account country assignment first, else the country of the account's phone number.
An unknown country returns None and the dashboard keeps its previous default (the
browser's zone).
"""

from __future__ import annotations

COUNTRY_KEY = "account.country_code"

COUNTRY_TIMEZONES = {
    "TZ": "Africa/Dar_es_Salaam",
    "KE": "Africa/Nairobi",
    "UG": "Africa/Kampala",
    "RW": "Africa/Kigali",
    "BI": "Africa/Bujumbura",
    "CD": "Africa/Kinshasa",
    "ZM": "Africa/Lusaka",
    "MW": "Africa/Blantyre",
    "MZ": "Africa/Maputo",
    "ET": "Africa/Addis_Ababa",
    "NG": "Africa/Lagos",
    "GH": "Africa/Accra",
    "ZA": "Africa/Johannesburg",
}


def country_timezone(country: str | None) -> str | None:
    return COUNTRY_TIMEZONES.get((country or "").strip().upper())


def phone_country(phone: str | None) -> str | None:
    if not phone:
        return None
    try:
        import phonenumbers
        return phonenumbers.region_code_for_number(phonenumbers.parse(phone, None)) or None
    except Exception:
        return None


def account_country(user) -> str | None:
    assigned = next((item.value for item in (getattr(user, "meta", None) or [])
                     if item.key == COUNTRY_KEY and item.value and item.value != "*"), None)
    return (assigned or phone_country(getattr(user, "phone", None)) or "").upper() or None


def account_timezone(user) -> str | None:
    return country_timezone(account_country(user))
