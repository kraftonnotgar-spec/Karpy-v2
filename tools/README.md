# tools

- `check_neutral.py` (wrapper: `check_neutral`) — fails when product names from `neutral_terms.txt`
  appear in core code (`backend/app`, `backend/karpy_platform`, `backend/tools`, `web/src` except
  `web/src/products/`, `mobile/src`, `mobile/modules`, `mobile/plugins`, `services/`; Markdown excepted),
  or when raw hex colours appear in `web/src` / `mobile/src` TypeScript outside the theme folders.
  Run `python tools/check_neutral.py` before every commit; `--list` prints the rules.
- `neutral_terms.txt` — one case-insensitive regular expression per line.
