import type { NavGroup } from "@/core/features/navigation";

/**
 * Static items on the admin console's Workspace level. Plugin sections come from the backend
 * registry at runtime (GET /api/admin/console/menu, see src/core/admin); products add static
 * items through their manifest (`nav.adminWorkspace`). `href` is relative to the admin base path.
 */
export const coreAdminWorkspace: NavGroup[] = [
  {
    id: "workspace",
    labelKey: "admin.workspace",
    order: 10,
    items: [{ id: "overview", labelKey: "admin.nav.overview", href: "/admin", icon: "layout-dashboard", order: 10, matchNested: false }],
  },
];
