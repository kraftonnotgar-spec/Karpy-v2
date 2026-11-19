<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Rules for this web app

Read `README.md` first. In short:

- **Product-neutral core.** No product or brand names in `src/core`, `src/components`, `src/app`, identifiers, CSS classes, cookies or storage keys. Brand values come from `src/core/config/brand.ts` (env + product manifest).
- **Tokens only.** Colour values live only in `src/products/<p>/theme.css`. Components use semantic Tailwind tokens (`bg-primary`, `text-muted-foreground`, `text-success`…).
- **Catalogs only.** UI text comes from `src/core/i18n/messages/*.json` or `src/products/<p>/messages/*.json` via `t()` / `useT()`. ESLint (`react/jsx-no-literals`) rejects literal JSX text in `src/core`, `src/products` and `src/app`.
- **`src/components/ui` is shadcn, unmodified.** Do not restyle or edit; compose in `src/core/components`.
- **Admin menu and Overview are data.** Plugins register sections and widgets in the backend registry (`/api/admin/console/menu`, `/api/admin/console/widgets`); no per-plugin web code.
- Before finishing: `npm run typecheck`, `npm run lint`, `npm run build`.
