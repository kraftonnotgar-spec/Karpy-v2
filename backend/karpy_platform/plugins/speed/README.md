# Speed

Generated KARPy plugin scaffold.

## Required metadata

- Plugin ID: `krafton/speed`
- Folder: `speed`
- Provider: `karpy_platform.plugins.speed.provider`
- Version: `1.0.0`

## Commands

```bash
python -m karpy_platform plugin:activate speed
python -m karpy_platform crud:create Example --plugin speed
```

## Structure

- `plugin.json` is read by the KARPy plugin manager.
- `provider.py` is the plugin service provider.
- `routes.py` exposes plugin API routes under `/api/plugins/speed` when active.
- `models/` contains SQLAlchemy models. Activation imports these models and creates missing plugin tables.
- `schemas/`, `services/`, `admin/`, and `database/migrations/` are ready for CRUD work.
