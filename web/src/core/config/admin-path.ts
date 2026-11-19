/**
 * Where the admin console is served. The route files live in src/app/admin; ADMIN_BASE_PATH
 * (validated in next.config.ts and exposed as NEXT_PUBLIC_ADMIN_BASE_PATH) serves them under
 * another single segment through a rewrite.
 */
export const ADMIN_ROUTE_ROOT = "/admin";

export function adminBasePath(): string {
  return process.env.NEXT_PUBLIC_ADMIN_BASE_PATH || ADMIN_ROUTE_ROOT;
}

/**
 * Turns a registry route ("/admin/contacts", as plugins declare it) or a relative one
 * ("/contacts") into the URL the browser uses.
 */
export function adminHref(route: string): string {
  const base = adminBasePath();
  if (route === ADMIN_ROUTE_ROOT || route === "") return base;
  if (route.startsWith(`${ADMIN_ROUTE_ROOT}/`)) return base + route.slice(ADMIN_ROUTE_ROOT.length);
  if (route.startsWith(`${base}/`) || route === base) return route;
  return base + (route.startsWith("/") ? route : `/${route}`);
}
