import type { MetadataRoute } from "next";
import { manifestColors } from "@/core/config/theme-colors";
import { brand, locale, product, t } from "@/products";

export const dynamic = "force-static";

// PWA manifest from brand config; colours from the product's theme.css. Icons are added when a
// product supplies logo files (public/brand/<product>/).
export default function manifest(): MetadataRoute.Manifest {
  const colors = manifestColors(product.key);
  return {
    id: "/",
    name: brand.name,
    short_name: brand.shortName,
    description: brand.tagline ?? t("brand.tagline"),
    start_url: "/?source=pwa",
    scope: "/",
    display: "standalone",
    orientation: "any",
    ...(colors.background ? { background_color: colors.background } : {}),
    ...(colors.theme ? { theme_color: colors.theme } : {}),
    lang: locale,
  };
}
