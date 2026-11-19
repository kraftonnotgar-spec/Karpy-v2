# Starting a new project from Karpy-v2

Example: a new product called **Acme**. Karpy-v2 stays the `upstream`; Acme lives in its own folder
and repository.

## 1. Clone and keep the platform as upstream

```bash
git clone https://github.com/kraftonnotgar-spec/Karpy-v2.git acme && cd acme
git remote rename origin upstream                   # Karpy-v2 = upstream
git remote add origin https://github.com/<owner>/acme.git
git push -u origin main
```

Later, take platform improvements:

```bash
git fetch upstream --tags
git merge v0.2.0                                    # tagged releases; read CHANGELOG.md first
cd backend && .venv/bin/python -m app.migrations up
```

Merge tagged releases only. Never edit core files inside the product: extend through plugins, hooks,
settings, seed data and ports. A core bug found in Acme is fixed in Karpy-v2 first, released, merged.

## 2. Add the product layer

| What | Where |
|---|---|
| Brand name, tagline, URLs (server side) | `backend/.env` (`APP_NAME`, `APP_URL`, `PUBLIC_SITE_URL`, …); admin-editable values in Settings (`site_title`, email settings) |
| Brand tokens (colours, fonts, radius) | copy `web/src/products/default/` → `web/src/products/acme/`, edit `theme.css` (the only web file with colour values) |
| Product manifest, navigation additions | `web/src/products/acme/product.ts`; set `NEXT_PUBLIC_PRODUCT=acme` |
| Copy / translations | `web/src/products/acme/messages/<locale>.json` (overrides core catalogs) |
| Logos and icons | `web/public/brand/acme/` |
| Mobile name, bundle ids, colours | `mobile/app.json` (`expo.name`, `slug`, `ios.bundleIdentifier`, `android.package`), `mobile/src/theme/`, `mobile/.env` (`EXPO_PUBLIC_API_URL`) |
| Product features | product plugins: `backend/karpy_platform/plugins/acme_<feature>/` (or a separate plugins root), each with migrations, routes, `get_admin_sections()`, `get_overview_widgets()` |
| Product rules for sign-in/sign-up | hooks from `plugins/auth/extensions.py` registered in your plugin's `boot()` |
| Other-language services | copy `services/go-template` → `services/acme-<name>`, add its OpenAPI contract |
| Product names in the neutrality check | add `acme` to `tools/neutral_terms.txt` in the *platform*, not the product, if the product's name must never leak into core |

## 3. Choose plugins

Edit `backend/karpy_platform/activated_plugins.json` or use
`python -m karpy_platform plugin:activate <name>` / `plugin:deactivate <name>`. Deactivated plugins
disappear from the admin menu and Overview automatically.

## 4. Secrets and environments

Copy each `.env.example` to `.env` (root, `backend/`, `web/`, `mobile/`) and set real secrets
(`SECRET_KEY`, `JWT_SECRET`, database, Redis, RabbitMQ, `SERVICE_SIGNING_SECRET`). Provider API keys
entered in the admin are stored encrypted (`core/security/secrets.py`). Nothing secret goes into git.

## 5. Check before the first deploy

```bash
python tools/check_neutral.py
cd backend && .venv/bin/python -m pytest -q
cd web && npm run typecheck && npm run lint && npm run build
cd mobile && npx tsc --noEmit && npm run lint && npm test
```

## 6. Deploy

One deployment per brand: own database, media storage, secrets and domains. Run migrations, then create
the first Super Admin (`ADMIN_BOOTSTRAP_USERNAME/EMAIL/PASSWORD`), then activate the plugins.
`APP_ENV=production` turns on strict checks (HTTPS URLs, strong secrets, PostgreSQL, explicit CORS).
