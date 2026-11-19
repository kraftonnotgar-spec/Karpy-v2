# Social Login

Google OAuth 2.0/OpenID Connect authentication for KARPy CMS. The plugin owns
its account links, one-use OAuth flows, routes, and Settings -> Others card.

## Google setup

1. Create an OAuth 2.0 Client ID with application type **Web application** in
   Google Cloud Console.
2. Copy the exact callback URL displayed in KARPy's Social Login settings into
   **Authorized redirect URIs**.
3. Add the client ID and client secret in Settings -> Social Login.
4. Enable Social Login and Google Login. Keep new user registration disabled
   unless Google users should be allowed to create CMS accounts.

The implementation validates state, PKCE, nonce, issuer, audience, signature,
expiry, and Google's verified-email claim before linking an identity.

Generated KARPy plugin scaffold.

## Required metadata

- Plugin ID: `krafton/social-login`
- Folder: `social_login`
- Provider: `karpy_platform.plugins.social_login.provider`
- Version: `1.0.0`

## Commands

```bash
python -m karpy_platform plugin:activate social_login
python -m karpy_platform crud:create Example --plugin social_login
```

## Structure

- `plugin.json` is read by the KARPy plugin manager.
- `provider.py` is the plugin service provider.
- `routes.py` exposes plugin API routes under `/api/plugins/social_login` when active.
- `models/` contains SQLAlchemy models. Activation imports these models and creates missing plugin tables.
- `schemas/`, `services/`, `admin/`, and `database/migrations/` are ready for CRUD work.
