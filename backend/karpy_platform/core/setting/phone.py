from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
    import phonenumbers
except ImportError:  # pragma: no cover - dependency is listed, fallback keeps boot safe.
    phonenumbers = None


@dataclass(frozen=True)
class PhoneCountry:
    iso2: str
    dial_code: str
    name: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "iso2": self.iso2,
            "dialCode": self.dial_code,
            "name": self.name or self.iso2,
        }


FALLBACK_COUNTRIES = [
    PhoneCountry("TZ", "+255", "Tanzania"),
    PhoneCountry("US", "+1", "United States"),
    PhoneCountry("GB", "+44", "United Kingdom"),
    PhoneCountry("KE", "+254", "Kenya"),
    PhoneCountry("UG", "+256", "Uganda"),
    PhoneCountry("RW", "+250", "Rwanda"),
    PhoneCountry("BI", "+257", "Burundi"),
    PhoneCountry("ZA", "+27", "South Africa"),
    PhoneCountry("NG", "+234", "Nigeria"),
    PhoneCountry("GH", "+233", "Ghana"),
    PhoneCountry("IN", "+91", "India"),
    PhoneCountry("AE", "+971", "United Arab Emirates"),
    PhoneCountry("SA", "+966", "Saudi Arabia"),
    PhoneCountry("DE", "+49", "Germany"),
    PhoneCountry("FR", "+33", "France"),
    PhoneCountry("IT", "+39", "Italy"),
    PhoneCountry("ES", "+34", "Spain"),
    PhoneCountry("RS", "+381", "Serbia"),
    PhoneCountry("SC", "+248", "Seychelles"),
    PhoneCountry("SL", "+232", "Sierra Leone"),
    PhoneCountry("SG", "+65", "Singapore"),
    PhoneCountry("SX", "+1", "Sint Maarten"),
]


DEFAULT_PHONE_SETTINGS = {
    "phone_country_code_enabled": "1",
    "phone_available_countries_all": "1",
    "phone_available_countries": [],
    "phone_min_length": "9",
    "phone_max_length": "15",
    "phone_default_country": "TZ",
}


def available_phone_countries() -> list[PhoneCountry]:
    if phonenumbers is None:
        return FALLBACK_COUNTRIES

    countries: list[PhoneCountry] = []
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        dial_code = phonenumbers.country_code_for_region(region)
        if not dial_code:
            continue
        countries.append(PhoneCountry(region.upper(), f"+{dial_code}", region.upper()))
    return countries


def phone_country_options() -> list[dict[str, str]]:
    return [country.to_dict() for country in available_phone_countries()]


def phone_settings_payload(values: dict[str, Any]) -> dict[str, Any]:
    resolved = {**DEFAULT_PHONE_SETTINGS, **(values or {})}
    all_countries = phone_country_options()
    selected = normalize_country_codes(resolved.get("phone_available_countries"))
    if _truthy(resolved.get("phone_available_countries_all")) or not selected:
        active_countries = all_countries
    else:
        allowed = set(selected)
        active_countries = [country for country in all_countries if country["iso2"] in allowed]
    if not active_countries:
        active_countries = all_countries

    default_country = str(resolved.get("phone_default_country") or "TZ").upper()
    if default_country not in {country["iso2"] for country in active_countries}:
        default_country = active_countries[0]["iso2"] if active_countries else "TZ"

    return {
        "settings": {
            "countryCodeEnabled": _truthy(resolved.get("phone_country_code_enabled")),
            "allCountries": _truthy(resolved.get("phone_available_countries_all")),
            "selectedCountries": selected,
            "minimumLength": _int_value(resolved.get("phone_min_length"), 9),
            "maximumLength": _int_value(resolved.get("phone_max_length"), 15),
            "defaultCountry": default_country,
        },
        "countries": all_countries,
        "activeCountries": active_countries,
    }


def validate_phone_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    countries = {country.iso2 for country in available_phone_countries()}
    min_length = _int_value(values.get("phone_min_length"), 9)
    max_length = _int_value(values.get("phone_max_length"), 15)

    if "phone_min_length" in values and min_length < 1:
        errors["phone_min_length"] = "Minimum length must be at least 1."
    if "phone_max_length" in values and max_length < 1:
        errors["phone_max_length"] = "Maximum length must be at least 1."
    if min_length > max_length:
        errors["phone_max_length"] = "Maximum length must be greater than or equal to minimum length."

    selected = normalize_country_codes(values.get("phone_available_countries"))
    invalid = [code for code in selected if code not in countries]
    if invalid:
        errors["phone_available_countries"] = f"Invalid country code: {', '.join(invalid[:5])}."
    if values.get("phone_available_countries_all") in {False, "0", 0} and not selected:
        errors["phone_available_countries"] = "Choose at least one country or enable all countries."

    default_country = str(values.get("phone_default_country") or "").upper()
    if default_country and default_country not in countries:
        errors["phone_default_country"] = "Invalid default country."

    return errors


def validate_phone_number(value: str | None, settings: dict[str, Any]) -> str | None:
    if value is None or str(value).strip() == "":
        return None

    payload = phone_settings_payload(settings)
    phone_settings = payload["settings"]
    enabled = bool(phone_settings["countryCodeEnabled"])
    min_length = int(phone_settings["minimumLength"])
    max_length = int(phone_settings["maximumLength"])
    allowed_regions = {country["iso2"] for country in payload["activeCountries"]}
    raw = str(value).strip()

    if enabled:
        compact = _compact_international(raw)
        digits = re.sub(r"\D", "", compact)
        if not compact.startswith("+"):
            raise ValueError("The phone number must include a country code.")
        _check_length(digits, min_length, max_length)

        if phonenumbers is not None:
            try:
                parsed = phonenumbers.parse(compact, None)
            except phonenumbers.NumberParseException as exception:
                raise ValueError("Invalid phone number.") from exception
            region = phonenumbers.region_code_for_number(parsed)
            if region and region.upper() not in allowed_regions:
                raise ValueError("The selected phone country is not available.")
            if not phonenumbers.is_possible_number(parsed):
                raise ValueError("Invalid phone number length for the selected country.")
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

        if not any(compact.startswith(country.dial_code) for country in FALLBACK_COUNTRIES if country.iso2 in allowed_regions):
            raise ValueError("The selected phone country is not available.")
        return compact

    digits = re.sub(r"\D", "", raw)
    _check_length(digits, min_length, max_length)
    if not re.match(r"^[0-9\s\-+()]+$", raw):
        raise ValueError("The phone number may only contain digits, spaces, dashes, plus signs, and parentheses.")
    return raw


def normalize_country_codes(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        items = re.split(r"[\s,;]+", value)
    elif isinstance(value, list):
        items = value
    else:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        code = str(item).strip().upper()
        if len(code) == 2 and code.isalpha() and code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _compact_international(value: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", value)
    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"
    if not cleaned.startswith("+") and cleaned:
        cleaned = f"+{cleaned}"
    return cleaned


def _check_length(digits: str, minimum: int, maximum: int) -> None:
    if len(digits) < minimum:
        raise ValueError(f"The phone number must be at least {minimum} characters.")
    if len(digits) > maximum:
        raise ValueError(f"The phone number must be at most {maximum} characters.")


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    return value is True or value == "1" or value == 1
