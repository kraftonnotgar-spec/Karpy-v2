import { z } from "zod";

/**
 * Brand / runtime config, validated once at start-up (module load): a bad value fails the
 * build or boot with a clear message instead of rendering a broken page.
 * NEXT_PUBLIC_* values are read literally so Next.js can inline them into the browser bundle.
 */
export const DEFAULT_APP_NAME = "Karpy";

const optionalText = z.string().trim().min(1).max(120).optional();

export const brandSchema = z.object({
  name: z.string().trim().min(1).max(60),
  shortName: z.string().trim().min(1).max(24),
  tagline: optionalText,
  supportEmail: z.email().optional(),
  locale: z.string().regex(/^[a-z]{2}(-[A-Z]{2})?$/, "use a locale code such as en or sw"),
});
export type BrandConfig = z.infer<typeof brandSchema>;

const env = (value: string | undefined) => (value && value.trim() ? value.trim() : undefined);

export function loadBrandConfig(defaults: { name?: string; shortName?: string; tagline?: string; supportEmail?: string; locale: string }): BrandConfig {
  const name = env(process.env.NEXT_PUBLIC_APP_NAME) ?? defaults.name ?? DEFAULT_APP_NAME;
  const raw = {
    name,
    shortName: env(process.env.NEXT_PUBLIC_APP_SHORT_NAME) ?? defaults.shortName ?? name,
    tagline: env(process.env.NEXT_PUBLIC_APP_TAGLINE) ?? defaults.tagline,
    supportEmail: env(process.env.NEXT_PUBLIC_SUPPORT_EMAIL) ?? defaults.supportEmail,
    locale: env(process.env.NEXT_PUBLIC_LOCALE) ?? defaults.locale,
  };
  const parsed = brandSchema.safeParse(raw);
  if (!parsed.success) {
    const problems = parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ");
    throw new Error(`Invalid brand config (NEXT_PUBLIC_APP_* / product brand): ${problems}`);
  }
  return parsed.data;
}
