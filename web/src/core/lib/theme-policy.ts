export type ThemePolicy = {
  default_theme: "light" | "dark";
  theme_mode: "both" | "light" | "dark";
};

export const defaultThemePolicy: ThemePolicy = { default_theme: "light", theme_mode: "both" };

/** Browser storage keys (product-neutral; one deployment = one brand = one origin). */
export const THEME_STORAGE_KEY = "app-theme";
export const THEME_POLICY_STORAGE_KEY = "app-theme-policy";

export function resolveTheme(preference: string | null, policy: ThemePolicy, systemDark: boolean): "light" | "dark" {
  if (policy.theme_mode !== "both") return policy.theme_mode;
  if (preference === "light" || preference === "dark") return preference;
  if (preference === "system") return systemDark ? "dark" : "light";
  return policy.default_theme;
}
