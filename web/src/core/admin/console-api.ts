import { z } from "zod";
import { api, adminAuthAPI, API_BASE, postJSON } from "@/core/lib/api";
import { withRange, type DateRange } from "@/core/lib/date-range";
import {
  adminStatusSchema,
  badgeCountSchema,
  chartDataSchema,
  consoleMenuSchema,
  consoleWidgetsSchema,
  kpiDataSchema,
  listDataSchema,
  todoDataSchema,
  type WidgetType,
} from "./console-types";

/** Every admin console call lives here. All are same-origin and use the admin session cookie. */

export const consoleAPI = `${API_BASE}/admin/console`;

export async function fetchAdminStatus(signal?: AbortSignal) {
  return (await api(`${adminAuthAPI}/status`, adminStatusSchema, { signal })).data;
}

export async function fetchConsoleMenu(signal?: AbortSignal) {
  return (await api(`${consoleAPI}/menu`, consoleMenuSchema, { signal })).data.sections;
}

export async function fetchConsoleWidgets(signal?: AbortSignal) {
  return (await api(`${consoleAPI}/widgets`, consoleWidgetsSchema, { signal })).data.widgets;
}

export async function fetchBadgeCount(endpoint: string, signal?: AbortSignal) {
  return (await api(endpoint, badgeCountSchema, { signal })).data.count;
}

const widgetSchemas = {
  kpi: kpiDataSchema,
  area_chart: chartDataSchema,
  line_chart: chartDataSchema,
  bar_chart: chartDataSchema,
  list: listDataSchema,
  todo: todoDataSchema,
} as const satisfies Record<WidgetType, z.ZodType>;
export type WidgetData<T extends WidgetType> = z.infer<(typeof widgetSchemas)[T]>;

export async function fetchWidgetData<T extends WidgetType>(type: T, endpoint: string, range: DateRange, signal?: AbortSignal): Promise<WidgetData<T>> {
  const schema = widgetSchemas[type] as unknown as z.ZodType<WidgetData<T>>;
  return (await api(withRange(endpoint, range), schema, { signal })).data;
}

// ---- Admin sign-in (POST /api/admin/auth/login, then /login/setup on first sign-in) ----------

const adminLoginSchema = z.object({
  mfa_required: z.boolean().optional(),
  mfa_setup_required: z.boolean().optional(),
  setup_token: z.string().optional(),
  secret: z.string().optional(),
  qr: z.string().optional(),
  user: z.unknown().optional(),
});
export type AdminLoginResult = z.infer<typeof adminLoginSchema>;

export async function adminLogin(body: { login: string; password: string; code?: string }) {
  return (await postJSON(`${adminAuthAPI}/login`, body, adminLoginSchema)).data;
}

const setupResultSchema = z.object({ recovery_codes: z.array(z.string()).optional() });
export async function adminCompleteSetup(body: { token: string; code: string }) {
  return (await postJSON(`${adminAuthAPI}/login/setup`, body, setupResultSchema)).data;
}

export async function adminLogout() {
  await postJSON(`${adminAuthAPI}/logout`, {});
}
