# Contact

Generated KARPy plugin scaffold.

## Required metadata

- Plugin ID: `krafton/contact`
- Folder: `contact`
- Provider: `karpy_platform.plugins.contact.provider`
- Version: `1.0.0`

## Commands

```bash
python -m karpy_platform plugin:activate contact
python -m karpy_platform crud:create Example --plugin contact
```

## Structure

- `plugin.json` is read by the KARPy plugin manager.
- `provider.py` is the plugin service provider.
- `routes.py` exposes plugin API routes under `/api/plugins/contact` when active.
- `models/` contains SQLAlchemy models. Activation imports these models and creates missing plugin tables.
- `schemas/`, `services/`, `admin/`, and `database/migrations/` are ready for CRUD work.
