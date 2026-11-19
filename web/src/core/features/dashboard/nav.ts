import type { NavGroup } from "@/core/features/navigation";

/** Core dashboard menu. Products add groups/items through their manifest (`nav.dashboard`). */
export const coreDashboardNav: NavGroup[] = [
  {
    id: "workspace",
    labelKey: "dashboard.nav.workspace",
    order: 10,
    items: [{ id: "overview", labelKey: "dashboard.nav.overview", href: "/dashboard", icon: "layout-dashboard", order: 10, matchNested: false }],
  },
  {
    id: "account",
    labelKey: "dashboard.nav.account",
    order: 90,
    items: [{ id: "settings", labelKey: "dashboard.nav.settings", href: "/dashboard/settings", icon: "settings", order: 90 }],
  },
];
