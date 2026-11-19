import type { MessageTree } from "@/core/i18n";
import type { NavGroup } from "@/core/features/navigation";

/**
 * The contract a product (src/products/<key>/product.ts) fulfils. Core reads products only
 * through this shape; core never imports product code (src/products/index.ts wires them).
 */
export type ProductManifest = {
  /** Matches NEXT_PUBLIC_PRODUCT and the <html data-product> attribute its theme.css is scoped to. */
  key: string;
  /** Brand defaults; NEXT_PUBLIC_* env values override them (src/core/config/brand.ts). */
  brand: {
    name: string;
    shortName?: string;
    tagline?: string;
    supportEmail?: string;
  };
  /** Locales the product ships; the first is the default. Each must exist in the core catalogs. */
  locales: readonly [string, ...string[]];
  /** Product copy and overrides of core messages, per locale. */
  messages?: Partial<Record<string, MessageTree>>;
  /** Navigation additions, merged into the core menus by group id. */
  nav?: {
    dashboard?: NavGroup[];
    /** Extra items on the admin console's Workspace level (backend sections come at runtime). */
    adminWorkspace?: NavGroup[];
  };
};
