import { loadBrandConfig } from "@/core/config/brand";
import type { ProductManifest } from "@/core/config/product";
import { coreAdminWorkspace } from "@/core/admin/menu";
import { coreDashboardNav } from "@/core/features/dashboard/nav";
import { mergeNav } from "@/core/features/navigation";
import { buildMessages, coreLocales, createTranslator } from "@/core/i18n";
import { defaultProduct } from "./default/product";

/**
 * Product registry. Add a product by importing its manifest here and its theme.css in
 * src/app/globals.css; NEXT_PUBLIC_PRODUCT picks the active one (default "default").
 * This is the only place that wires core and product together.
 */
const products: Record<string, ProductManifest> = {
  [defaultProduct.key]: defaultProduct,
};

const key = process.env.NEXT_PUBLIC_PRODUCT?.trim() || "default";
const selected = products[key];
if (!selected) {
  throw new Error(`Unknown NEXT_PUBLIC_PRODUCT "${key}". Known products: ${Object.keys(products).join(", ")}.`);
}
export const product: ProductManifest = selected;

export const brand = loadBrandConfig({ ...product.brand, locale: product.locales[0] });
if (!product.locales.includes(brand.locale) || !(coreLocales as string[]).includes(brand.locale)) {
  throw new Error(`Locale "${brand.locale}" is not offered by product "${product.key}" (${product.locales.join(", ")}) or has no core catalog.`);
}

export const locale = brand.locale;
export const messages = buildMessages(locale, product.messages);
/** Server-side translator for the active locale. Client components use useT() instead. */
export const t = createTranslator(messages, locale);

export const dashboardNav = mergeNav(coreDashboardNav, product.nav?.dashboard);
export const adminWorkspaceNav = mergeNav(coreAdminWorkspace, product.nav?.adminWorkspace);
