# Reusing Karpy-v2: the core / product-layer split

Karpy-v2 is a **product-neutral platform**. A real project is a **thin product layer** on top of it:
configuration, seed data, optional demo data, and a few product plugins. The neutral core knows no product
by name — it is told which product to load through the `PRODUCT` setting, and reads everything
product-specific from that product's folder.

This document covers the **backend product layer**: `backend/products/<PRODUCT>/`, the seed/demo loader and
its console commands. For the full fork workflow (web, mobile, services, brand tokens), see
[`NEW_PROJECT.md`](NEW_PROJECT.md).

---

## 1. Where a product lives

```
backend/products/<PRODUCT>/
  product.json        # manifest: key, locales, currency, which seed/demo files to load
  seed/*.json         # seed data: inserted once, never overwrites later admin edits
  demo/*.json         # optional demo data for staging (opt-in, never in production)
```

The core ships one minimal, neutral example product, [`backend/products/_example/`](../backend/products/_example),
used by the core tests and as a template to copy.

`PRODUCT` selects the folder. It has **no default on purpose**: the seed commands fail with a clear message
until it is set, so the neutral core never assumes a product.

```bash
export PRODUCT=_example          # a folder under backend/products
# or pass --product _example to each command
```

## 2. `product.json`

```json
{
  "key": "_example",
  "name": "Example Product",
  "seed_version": 1,
  "default_locale": "en",
  "locales": ["en"],
  "currency": "USD",
  "country": "US",
  "timezone": "UTC",
  "enabled_plugins": ["auth"],
  "seed": ["settings.json", "roles.json"],
  "demo": { "email_domain": "demo.example", "phone_range": "+15550100000-+15550199999", "files": ["demo.json"] }
}
```

- `seed` / `demo.files` list the JSON files to load, relative to `seed/` and `demo/` (no path escaping).
- The manifest is validated at load time; `default_locale` must be one of `locales`.

## 3. Seed files pick loaders by top-level key

A seed file is a JSON object. Its **top-level keys** choose the loader, so file names are free. The neutral
core ships two loaders, both backed by core tables:

| key | what it does | needs table |
|---|---|---|
| `settings` | insert missing rows into the setting store | `settings` |
| `staff_roles` | insert missing ACL roles by slug | `roles` |

Keys `seed_version` and `source` are metadata. Every loader **inserts only what is missing by a stable key and
never overwrites an existing row**, so re-running the seed is safe and keeps admins' later edits. A loader
whose table is absent is skipped and reported.

A plugin or product adds its own loaders (so its seed data flows through the same command) with:

```python
from karpy_platform.core.products import register_seed_loader
register_seed_loader("catalog", "catalog", seed_catalog_loader, tables=("catalog_categories",))
```

An **unknown** top-level key (no loader registered) is a hard error, so a typo never silently drops data.

## 4. Demo data (staging only)

Demo is not seed. `demo:seed` first runs the seed, then loads the product's `demo/*.json`. It is **refused when
`APP_ENV` is production**. Demo accounts must use the product's `email_domain` and `phone_range` (the loader
rejects anything else), and get an unusable random password unless `DEMO_PASSWORD` is set. `demo:clear` removes
exactly those demo accounts (matched by the demo e-mail domain) and anything a registered demo clearer removes;
real accounts are untouched.

The core ships one demo loader, `users` (core ACL accounts). Products/plugins add demo content and its cleanup
with `register_demo_loader(key, loader, clearer=..., tables=...)`.

## 5. Commands

```bash
export PRODUCT=<product>
python -m karpy_platform product:seed          # load seed data (idempotent)
python -m karpy_platform demo:seed             # seed + demo data (dev/staging only)
python -m karpy_platform demo:clear            # remove demo accounts/content
```

Each command takes `--product <name>` to override `PRODUCT`. Run migrations first
(`python -m app.migrations up`); it also runs at start-up.

## 6. Add a product

1. Copy `backend/products/_example` → `backend/products/<yourproduct>` and edit `product.json`
   (`key`, locales, currency, which files to load).
2. Fill `seed/*.json` with your settings and roles (and any keys handled by loaders your plugins register).
3. Optionally fill `demo/*.json` with sample accounts for staging.
4. Set `PRODUCT=<yourproduct>`, run `python -m app.migrations up`, then `python -m karpy_platform product:seed`.
5. Keep the core neutral: nothing product-specific goes in `backend/karpy_platform/` — it lives in your product
   folder or in product plugins. `python tools/check_neutral.py` enforces this.

## Never

- Product names, categories, prices or business rules hardcoded in core (`backend/app`, `backend/karpy_platform`).
- Seed loaders that overwrite existing rows (they must insert-missing only, by a stable key).
- Demo data outside staging, or demo accounts that do not use the product's demo domain.
