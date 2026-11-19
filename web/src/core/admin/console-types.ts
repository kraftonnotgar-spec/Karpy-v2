import { z } from "zod";

/**
 * Admin console registry contract (backend: karpy_platform/core/dashboard/console.py).
 * Every response from the console endpoints and from plugin widget/badge endpoints is
 * validated here before it reaches the UI, so a misbehaving plugin shows an error state
 * instead of breaking the console.
 */

export const badgeToneSchema = z.enum(["default", "attention", "danger"]);
export type BadgeTone = z.infer<typeof badgeToneSchema>;

export const menuBadgeSchema = z.object({
  endpoint: z.string().startsWith("/api/"),
  tone: badgeToneSchema.catch("default"),
});
export type MenuBadge = z.infer<typeof menuBadgeSchema>;

export type ConsoleMenuItem = {
  id: string;
  label: string;
  label_default: string;
  icon: string | null;
  route: string;
  permission: string | null;
  badge: MenuBadge | null;
  priority: number;
  children: ConsoleMenuItem[];
};

export const consoleMenuItemSchema: z.ZodType<ConsoleMenuItem> = z.lazy(() =>
  z.object({
    id: z.string().min(1),
    label: z.string(),
    label_default: z.string().default(""),
    icon: z.string().nullish().transform((value) => value ?? null),
    route: z.string().default(""),
    permission: z.string().nullish().transform((value) => value ?? null),
    badge: menuBadgeSchema.nullish().transform((value) => value ?? null),
    priority: z.number().default(50),
    children: z.array(consoleMenuItemSchema).default([]),
  }),
);

export const consoleSectionSchema = z.object({
  id: z.string().min(1),
  label: z.string(),
  label_default: z.string().default(""),
  icon: z.string().nullish().transform((value) => value ?? null),
  priority: z.number().default(50),
  permission: z.string().nullish().transform((value) => value ?? null),
  plugin: z.string().default("core"),
  items: z.array(consoleMenuItemSchema).default([]),
});
export type ConsoleSection = z.infer<typeof consoleSectionSchema>;

export const consoleMenuSchema = z.object({ sections: z.array(consoleSectionSchema) });
export type ConsoleMenu = z.infer<typeof consoleMenuSchema>;

export const badgeCountSchema = z.object({ count: z.number().int().nonnegative() });

export const widgetTypeSchema = z.enum(["kpi", "area_chart", "line_chart", "bar_chart", "list", "todo"]);
export type WidgetType = z.infer<typeof widgetTypeSchema>;
export const widgetSizeSchema = z.enum(["sm", "md", "lg", "full"]);
export type WidgetSize = z.infer<typeof widgetSizeSchema>;

export const overviewWidgetSchema = z.object({
  id: z.string().min(1),
  type: widgetTypeSchema,
  title: z.string(),
  title_default: z.string().default(""),
  endpoint: z.string().startsWith("/api/"),
  size: widgetSizeSchema.catch("sm"),
  permission: z.string().nullish().transform((value) => value ?? null),
  order: z.number().default(50),
  options: z.record(z.string(), z.unknown()).default({}),
  plugin: z.string().default("core"),
});
export type OverviewWidget = z.infer<typeof overviewWidgetSchema>;

/**
 * Widgets of an unknown type (a newer plugin than this web build) are dropped, not fatal:
 * the list is parsed item by item.
 */
export const consoleWidgetsSchema = z.object({
  widgets: z.array(z.unknown()).transform((items) =>
    items.flatMap((item) => {
      const parsed = overviewWidgetSchema.safeParse(item);
      return parsed.success ? [parsed.data] : [];
    }),
  ),
});

// ---- Widget data shapes (answers of GET <endpoint>?from=&to=) --------------------------------

export const kpiFormatSchema = z.enum(["number", "currency", "percent"]);
export const kpiDataSchema = z.object({
  value: z.number(),
  previous: z.number().nullish(),
  format: kpiFormatSchema.catch("number").default("number"),
  /** ISO 4217 code for format "currency" (value in major units). */
  currency: z.string().length(3).optional(),
});
export type KpiData = z.infer<typeof kpiDataSchema>;

export const chartDataSchema = z.object({
  series: z.array(z.object({ key: z.string().min(1), label: z.string().default("") })).min(1),
  points: z.array(z.object({ x: z.union([z.string(), z.number()]) }).catchall(z.unknown())),
});
export type ChartData = z.infer<typeof chartDataSchema>;

export const listDataSchema = z.object({
  items: z.array(
    z.object({
      id: z.union([z.string(), z.number()]).transform(String),
      title: z.string(),
      subtitle: z.string().nullish(),
      href: z.string().nullish(),
      meta: z.string().nullish(),
    }),
  ),
});
export type ListData = z.infer<typeof listDataSchema>;

export const todoDataSchema = z.object({
  items: z.array(
    z.object({
      id: z.union([z.string(), z.number()]).transform(String),
      label: z.string(),
      count: z.number().int().nonnegative(),
      href: z.string(),
    }),
  ),
});
export type TodoData = z.infer<typeof todoDataSchema>;

export const adminStatusSchema = z.object({
  authenticated: z.boolean(),
  user: z.object({ email: z.string().nullish(), name: z.string().nullish(), username: z.string().nullish() }).passthrough().nullish(),
});
export type AdminStatus = z.infer<typeof adminStatusSchema>;
