from __future__ import annotations

import re
import string
import unicodedata

from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class NewPassword(BaseModel):
    password: str = Field(min_length=8, max_length=120, repr=False)
    confirmPassword: str = Field(min_length=8, max_length=120, repr=False)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if not (re.search(r"[A-Z]", value) and re.search(r"[a-z]", value)
                and re.search(r"[0-9]", value) and any(char in string.punctuation for char in value)):
            raise ValueError("Use uppercase and lowercase letters, a number and a symbol.")
        return value


class RegisterRequest(NewPassword):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    acceptTerms: bool = Field(default=False, strict=True)
    policyVersion: int = Field(default=0, ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        if (not value or not unicodedata.category(value[0]).startswith("L")
                or any(not unicodedata.category(char).startswith(("L", "M"))
                       and char not in " .'-\u2019" for char in value)):
            raise ValueError("Use letters, spaces, apostrophes, hyphens or periods for your name, not numbers.")
        return " ".join(value.split())

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str) -> str:
        value = " ".join(value.split())
        if not re.fullmatch(r"[+0-9()\-\s]{6,30}", value):
            raise ValueError("The phone field must be a valid phone number.")
        return value


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendCodeRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=120)
    remember: bool = False


class VerifyLoginRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)


class OperatorServiceLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=120)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(NewPassword):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


# Mobile app (see MOBILE_AUTH.md). device_id is a random id the app generates once per
# install and keeps in secure storage; the server only stores and signs its hash.
DeviceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)]
OpaqueToken = Annotated[str, Field(min_length=45, max_length=45, pattern=r"^m\.[A-Za-z0-9_-]{43}$", repr=False)]


class MobileDevice(BaseModel):
    device_id: DeviceId
    device_name: str = Field(default="", max_length=80)
    platform: Literal["ios", "android"]

    @field_validator("device_name")
    @classmethod
    def clean_device_name(cls, value: str) -> str:
        return " ".join("".join(char for char in value if char.isprintable()).split())


class MobileLoginRequest(MobileDevice):
    email: EmailStr
    password: str = Field(min_length=1, max_length=120, repr=False)
    device_token: str | None = Field(default=None, max_length=2048, repr=False)


class MobileVerifyLoginRequest(MobileDevice):
    challenge_token: OpaqueToken
    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)


class MobileResendLoginRequest(BaseModel):
    resend_token: OpaqueToken
    device_id: DeviceId


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256, repr=False)
    device_id: DeviceId


class MobileLogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=256, repr=False)
    device_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)


class PushDeviceRequest(BaseModel):
    device_id: DeviceId
    platform: Literal["ios", "android"]
    provider: Literal["expo", "fcm", "apns"]
    token: str = Field(min_length=8, max_length=512, repr=False)
    app_version: str | None = Field(default=None, max_length=40)


class PushDeviceRemoveRequest(BaseModel):
    device_id: DeviceId
