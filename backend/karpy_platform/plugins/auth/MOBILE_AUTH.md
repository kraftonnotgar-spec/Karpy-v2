# Mobile app authentication (v1)

Sign-in for the mobile app (`mobile/`). Base URL: `<APP_URL>/api/plugins/auth/mobile/v1`.
Code: `mobile_routes.py`. Tests: `test_mobile_auth.py`.

The password, lockout, rate-limit, account-status, email-verification and new-device code rules are
the web sign-in's own functions (`routes._password_sign_in`, `device_verification`), so they behave
the same and return the same errors. Only the transport differs:

- Tokens and the code-challenge state come back in the JSON body. No cookie is ever set.
- Every call carries `device_id`: a random id (32-128 chars of `A-Za-z0-9_-`) the app generates once
  per install and keeps in secure storage. The server stores only its hash. The sign-in code, resend
  token, trusted-device token, refresh token and push registration are bound to it.
- Sessions are always remembered (`AUTH_REMEMBER_DAYS`, 30 days) and appear in `GET /user/sessions`
  as `client: "mobile"`, `userAgent: "<APP_NAME> iOS app · <device name>"`
  (`AUTH_MOBILE_APP_LABEL` overrides the name).
- Staff/admin accounts are refused unless `AUTH_MOBILE_ALLOW_STAFF=true`; plugins can refuse more
  accounts with the `auth.mobile.allow_user` filter.

All responses are `Cache-Control: no-store`. Errors use FastAPI's `{"detail": ...}` shape.

## POST /login

```json
{"email": "a@example.com", "password": "...", "device_id": "<32+ chars>",
 "device_name": "Amina's iPhone", "platform": "ios", "device_token": "<optional>"}
```

Trusted device, `200`:

```json
{"message": "Signed in successfully.", "user": {...}, "token_type": "Bearer",
 "access_token": "<JWT>", "expires_in": 900, "refresh_token": "<sid>.<secret>",
 "refresh_expires_in": 2592000}
```

New device, `200` (a code was sent by email, and by SMS when an SMS provider plugin is installed and
the phone is verified):

```json
{"requiresOTP": true, "channels": ["email"], "resend_after": 60,
 "challenge_token": "m.<43 chars>", "challenge_expires_in": 300,
 "resend_token": "m.<43 chars>", "resend_expires_in": 900}
```

| Status | `detail` |
| --- | --- |
| 422 | `{"email": "These credentials do not match our records."}` (also unknown email) |
| 429 | `{"form": "Too many sign-in attempts. Please try again later."}`, `Retry-After` |
| 429 | `{"form": "Please wait before requesting another sign-in code."}` |
| 403 | `{"email": "Please verify your email before signing in.", "requiresVerification": true}` |
| 403 | `{"form": "<message>", "accountStatus": "deactivated" \| "banned", "code": "account_deactivated" \| "account_banned", "reason": "<admin reason>" \| null}` |
| 403 | `{"form": "Staff accounts sign in on the web.", "mobileAccess": "staff_not_allowed"}` |
| 503 | `{"form": "We could not deliver your sign-in code. Please try again later."}` |

## POST /verify-login

`{"challenge_token", "code": "123456", "device_id", "device_name", "platform"}` → `200` with the
session tokens plus `"device_token": "<JWT>", "device_token_expires_in": 2592000`. Keep
`device_token` in secure storage and send it with the next `/login` to skip the code for 30 days
(it stops working after a password change, "sign out other devices", 30 days, or another device id).
Errors: `422 {"code": "The sign-in code is invalid or expired."}`, `403` as for `/login`.

## POST /resend-login

`{"resend_token", "device_id"}` → the `/login` code-sent body with a new `challenge_token` and the
same `resend_token`. Errors: `422`, `429` (cooldown), `503` (delivery).

## POST /refresh

`{"refresh_token", "device_id"}` → `200 {"message": "Session refreshed.", "token_type": "Bearer",
"access_token", "expires_in", "refresh_token": "<new>", "refresh_expires_in"}`. Every refresh rotates
the refresh token; store the new one before using the new access token.

- `401 "This session is no longer valid."`: sign in again. Replaying a rotated token (or the wrong
  `device_id`) ends the session, unless another refresh of it happened in the last 10 seconds.
- `403 {"detail": "<message>", "code": "account_deactivated" | "account_banned", "reason"}`: the
  account is closed; the app shows its "account closed" screen. The push registration of this
  `device_id` is removed.

## POST /logout

`Authorization: Bearer <access token>` and/or `{"refresh_token", "device_id"}`. Always
`200 {"message": "Signed out successfully."}`.

## GET /me

Mobile bearer → `200` `{"user": {..., "timezone", "country"}}`.

## Push devices

- `POST /push-devices` (bearer) `{"device_id", "platform": "ios"|"android", "provider": "expo"|"fcm"|"apns", "token", "app_version"?}` → `{"registered": true}`.
  One row per installation (`auth_push_devices`); signing in as another account on the same phone moves it.
- `DELETE /push-devices` (bearer) `{"device_id"}` → `{"removed": true}`.

Sending is done by a push provider plugin reading `PushDevice` rows; the platform does not send.

## Calling other APIs from the app

Send `Authorization: Bearer <access token>` and no auth cookies. Plugins accept mobile bearers with
`security.current_user` (claim `client: "mobile"`); requests authenticated this way skip the
Origin/CSRF check. Every bearer request checks the session row, so revoked sessions get `401` at once.

## Extension points

`auth.mobile.integrity` (genuine-app checks such as Play Integrity / App Attest: raise
`HTTPException` to refuse), `auth.mobile.allow_user`, `auth.mobile.session_ended`
(`signed_out`, `new_device`, `account_closed`) -- see `extensions.py` and `docs/PLUGINS.md`.
