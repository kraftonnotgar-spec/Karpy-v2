import type { ProductManifest } from "@/core/config/product";
import en from "./messages/en.json";

/**
 * The neutral default product. A new project copies this folder to src/products/<key>/,
 * changes the brand, theme.css and messages, and registers it in src/products/index.ts.
 */
export const defaultProduct: ProductManifest = {
  key: "default",
  brand: {
    name: "Karpy",
    shortName: "Karpy",
  },
  locales: ["en", "sw"],
  messages: { en },
  nav: {
    dashboard: [
      {
        id: "account",
        items: [{ id: "help", labelKey: "product.nav.help", href: "/dashboard/help", icon: "life-buoy", order: 95 }],
      },
    ],
  },
};
