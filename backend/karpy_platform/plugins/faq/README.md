# FAQs

KARPy FAQ manager with categories, Botble-style admin screens, and shortcode rendering.

## Required metadata

- Plugin ID: `krafton/faq`
- Folder: `faq`
- Provider: `karpy_platform.plugins.faq.provider`
- Version: `1.0.0`

## Commands

```bash
python -m karpy_platform plugin:activate faq
python -m karpy_platform crud:create Example --plugin faq
```

## Structure

- `plugin.json` is read by the KARPy plugin manager.
- `provider.py` is the plugin service provider.
- `routes.py` exposes plugin API routes under `/api/plugins/faq` when active.
- `models/` contains SQLAlchemy models. Activation imports these models and creates missing plugin tables.
- `schemas/`, `services/`, `admin/`, and `database/migrations/` are ready for CRUD work.
- The `[faq]` shortcode renders visible FAQ blocks only. It intentionally does not output FAQ rich-result schema because Google removed FAQ rich result support.
