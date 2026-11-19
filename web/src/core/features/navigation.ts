import type { TranslationKey } from "@/core/i18n";

/** A link in a sidebar. `icon` is a lucide icon name (kebab-case, e.g. "layout-dashboard"). */
export type NavItem = {
  id: string;
  labelKey: TranslationKey;
  href: string;
  icon: string;
  order?: number;
  /** Active also on nested paths (default true; false for index pages like "/dashboard"). */
  matchNested?: boolean;
};
export type NavGroup = {
  id: string;
  labelKey?: TranslationKey;
  order?: number;
  items: NavItem[];
};

const byOrder = <T extends { order?: number }>(a: T, b: T) => (a.order ?? 50) - (b.order ?? 50);

/** Merges additions into base groups by id (items by id too) and sorts both by `order`. */
export function mergeNav(base: NavGroup[], additions: NavGroup[] = []): NavGroup[] {
  const groups = new Map(base.map((group) => [group.id, { ...group, items: [...group.items] }]));
  for (const addition of additions) {
    const existing = groups.get(addition.id);
    if (!existing) {
      groups.set(addition.id, { ...addition, items: [...addition.items] });
      continue;
    }
    const items = new Map(existing.items.map((item) => [item.id, item]));
    for (const item of addition.items) items.set(item.id, item);
    groups.set(addition.id, { ...existing, ...addition, items: [...items.values()] });
  }
  return [...groups.values()].sort(byOrder).map((group) => ({ ...group, items: [...group.items].sort(byOrder) }));
}

export function isActivePath(path: string, item: Pick<NavItem, "href" | "matchNested">) {
  const href = item.href.split("?")[0];
  return path === href || (item.matchNested !== false && path.startsWith(`${href}/`));
}
