/**
 * Pure translation helper (no React Native imports; tested in tests/i18n.test.ts).
 *
 * Catalogs are nested JSON objects; keys are dot paths ("auth.signIn.title"). `{name}`
 * placeholders are replaced from `params`. A missing key returns the key itself so it is
 * visible in development instead of crashing.
 */
export type Catalog = { [key: string]: string | Catalog };
export type Params = Record<string, string | number>;

export function lookup(catalog: Catalog, key: string): string | undefined {
  let node: string | Catalog | undefined = catalog;
  for (const part of key.split('.')) {
    if (!node || typeof node === 'string') return undefined;
    node = node[part];
  }
  return typeof node === 'string' ? node : undefined;
}

export function format(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

export function createTranslator(catalogs: Catalog[]) {
  return function t(key: string, params?: Params): string {
    for (const catalog of catalogs) {
      const value = lookup(catalog, key);
      if (value !== undefined) return format(value, params);
    }
    return key;
  };
}

export function hasKey(catalogs: Catalog[], key: string) {
  return catalogs.some((catalog) => lookup(catalog, key) !== undefined);
}
