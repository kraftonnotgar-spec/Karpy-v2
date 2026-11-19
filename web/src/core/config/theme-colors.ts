import { readFileSync } from "node:fs";
import { join } from "node:path";

/** Server only (node:fs).
 * PWA manifest colours come from the active product's theme.css (the only place colours live):
 * `--manifest-background` and `--manifest-theme`. Read at build time by src/app/manifest.ts.
 * Returns nothing when the file or variables are missing, so the manifest simply omits them.
 */
export function manifestColors(productKey: string): { background?: string; theme?: string } {
  try {
    const css = readFileSync(join(process.cwd(), "src", "products", productKey, "theme.css"), "utf8");
    const value = (name: string) => css.match(new RegExp(`--${name}:\\s*([^;]+);`))?.[1]?.trim();
    return { background: value("manifest-background"), theme: value("manifest-theme") };
  } catch {
    return {};
  }
}
