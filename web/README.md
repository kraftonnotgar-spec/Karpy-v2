# Karpy web

Next.js 16 + React 19 + Tailwind 4 + shadcn front end for the KARPy platform (backend in `../backend`,
API under `/api`). Product-neutral: brand, colours and copy come from config, the active product's
theme and message catalogs. Every new project starts here and adds a product in `src/products/`.

Sources: the shadcn components, shells, admin console and Overview patterns were ported from the
owner's earlier dashboard (`teepay/ui`), following the first port done for KoMi (`Komi/web`).

## Commands

```bash
cp .env.example .env.local   # optional; defaults work against a local backend on :9000
npm install
npm run dev                  # http://localhost:3000
npm run typecheck            # next typegen + tsc
npm run lint                 # eslint (includes the no-literal-UI-text rule)
npm run build                # production build (standalone output)
```

## Routes

| Route | What it is |
|---|---|
| `/` | Neutral landing page (`src/app/(site)`) |
| `/sign-in` | User sign-in → `POST /api/plugins/auth/user/login` |
| `/dashboard` | Signed-in user workspace (sidebar shell, empty overview) |
| `/admin` (or `ADMIN_BASE_PATH`) | Admin console: sidebar and Overview built from the backend registry |
| `/admin/sign-in` | Admin sign-in → `POST /api/admin/auth/login` (+ authenticator enrolment / code) |

## Folder map

```
src/
├─ app/                     routes only: thin files that mount core features
├─ components/ui/           shadcn components, unmodified (see "Rules")
├─ hooks/                   shadcn/use-mobile, use-tween, use-reduced-motion
├─ lib/utils.ts             cn() — where shadcn expects it
├─ core/
│  ├─ admin/                admin console: console-types.ts (zod), console-api.ts (all calls),
│  │                        admin-shell.tsx (runtime sidebar, slide-in panels, badges),
│  │                        overview.tsx + widgets/ (kpi, area/line/bar charts, list, todo), sign-in
│  ├─ components/           neutral composites: theme preference + pre-paint script, theme toggle,
│  │                        page header, empty/error/loading states, copy button, icon, brand mark,
│  │                        sidebar menu slider, workspace header, animated figure
│  ├─ config/               brand.ts (zod-validated NEXT_PUBLIC_* + product defaults), product.ts
│  │                        (manifest contract), admin-path.ts, theme-colors.ts (PWA colours)
│  ├─ features/             auth (sign-in form), dashboard (shell + nav), navigation types
│  ├─ i18n/                 typed loader (t, useT) + messages/en.json, messages/sw.json
│  └─ lib/                  api client (/api), format, clipboard, notify, date ranges, theme policy
└─ products/
   ├─ index.ts              registry: picks NEXT_PUBLIC_PRODUCT, builds brand, messages, menus
   └─ default/              neutral default brand: product.ts, theme.css, messages/en.json
```

## Rules

1. **Tokens only.** Colour values (hex/oklch) appear only in `src/products/<p>/theme.css`.
   `globals.css` maps the semantic shadcn tokens (`--background`, `--primary`, sidebar, chart…) to the
   theme's `--app-*` variables. Components use Tailwind token classes only.
2. **Catalogs only.** No literal UI text in `src/core`, `src/products` or `src/app` (ESLint
   `react/jsx-no-literals`). Server code uses `t` from `@/products`; client components use `useT()`.
   Registry labels from the backend use `t.dynamic(key, fallbackText)`.
3. **`src/components/ui` stays as shadcn ships it.** Compose in `src/core/components` instead.
   Two files differ from the source copy only by neutral names: `sonner.tsx` (imports
   `@/core/components/preferences`, classes `app-toast*`) and `combobox.tsx` (class `app-combobox`).
4. **Core never imports products.** Only `src/products/index.ts` and `src/app` wire them together.
5. **Neutral names.** No product or brand names in code, identifiers, CSS classes, cookies or
   storage keys (theme key: `app-theme`).

## Admin console (plugins appear as data)

The admin sidebar and Overview are built at runtime from the backend registry
(`backend/karpy_platform/core/dashboard/console.py`):

- `GET /api/admin/console/menu` → sections (one Workspace entry each; clicking slides in the section's
  panel with *Back to Workspace*; items with `children` slide in a nested submenu). Items with a
  `badge.endpoint` show its `{"count": n}` when > 0, tone `default`/`attention`/`danger` via tokens.
- `GET /api/admin/console/widgets` → Overview widgets; each loads `GET <endpoint>?from=&to=` for the
  selected range (7/30/90 days) with its own skeleton / empty / error + retry states.
- Labels are i18n keys looked up in the catalogs, falling back to `label_default` / `title_default`.
  Icons are lucide names (common ones bundled, others loaded on demand, unknown → fallback icon).
- Registry routes without a web screen open a placeholder page (`src/app/admin/(console)/[...path]`).

A plugin adds itself to the admin with metadata only (see the backend `hello_world` plugin). Add its
label keys to the catalogs (e.g. `hello_world.*` in `src/core/i18n/messages/en.json`).

## Add a product / brand

1. Copy `src/products/default` to `src/products/<key>`; set `key`, `brand`, `locales`, `nav` in
   `product.ts`; scope `theme.css` to `:root[data-product="<key>"]` and set its colours and fonts.
2. Register it in `src/products/index.ts` and add `@import "../products/<key>/theme.css";` to
   `src/app/globals.css`.
3. Put product copy in `src/products/<key>/messages/<locale>.json` (override core keys or add
   `product.*` keys). Logo files go in `public/brand/<key>/`.
4. Build with `NEXT_PUBLIC_PRODUCT=<key> npm run build`.
