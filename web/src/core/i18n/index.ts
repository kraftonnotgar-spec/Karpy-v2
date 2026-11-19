import en from "./messages/en.json";
import sw from "./messages/sw.json";

/**
 * Tiny typed message loader. English is the source of truth for the key set; other locales and
 * product overrides are merged over it, so a missing translation falls back to English.
 * Products add their own keys under `product.*` (src/products/<p>/messages/<locale>.json).
 */
export type Messages = typeof en;
export type MessageTree = { [key: string]: string | MessageTree };
export type DeepPartial<T> = { [K in keyof T]?: T[K] extends string ? string : DeepPartial<T[K]> };

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

/** Every key in the core catalogs, e.g. "auth.signIn.title". */
export type MessageKey = Leaves<Messages>;
/** Product-defined keys live under `product.`. */
export type ProductMessageKey = `product.${string}`;
export type TranslationKey = MessageKey | ProductMessageKey;
export type MessageValues = Record<string, string | number>;

export const coreCatalogs = { en, sw: sw as DeepPartial<Messages> } as const;
export type CoreLocale = keyof typeof coreCatalogs;
export const coreLocales = Object.keys(coreCatalogs) as CoreLocale[];

function merge(target: MessageTree, source: MessageTree | undefined): MessageTree {
  if (!source) return target;
  for (const [key, value] of Object.entries(source)) {
    const current = target[key];
    target[key] = typeof value === "object" && typeof current === "object" ? merge({ ...current }, value) : value;
  }
  return target;
}

/** English core → product English → core locale → product locale. */
export function buildMessages(locale: string, overrides: Partial<Record<string, MessageTree>> = {}): MessageTree {
  const base = merge(structuredClone(en) as MessageTree, overrides.en);
  if (locale === "en") return base;
  const core = (coreCatalogs as Record<string, unknown>)[locale] as MessageTree | undefined;
  return merge(merge(base, core), overrides[locale]);
}

/** Looks a dotted key up; undefined when missing (for registry labels with a default text). */
export function lookup(messages: MessageTree, key: string): string | undefined {
  let node: string | MessageTree | undefined = messages;
  for (const part of key.split(".")) {
    if (!node || typeof node === "string") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

export function interpolate(text: string, values?: MessageValues) {
  if (!values) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in values ? String(values[name]) : match));
}

export type Translator = {
  (key: TranslationKey, values?: MessageValues): string;
  /** Runtime keys (e.g. from the backend registry): the catalog text, else `fallback`, else the key. */
  dynamic: (key: string | null | undefined, fallback?: string, values?: MessageValues) => string;
  locale: string;
};

export function createTranslator(messages: MessageTree, locale: string): Translator {
  const t = ((key: TranslationKey, values?: MessageValues) => interpolate(lookup(messages, key) ?? key, values)) as Translator;
  t.dynamic = (key, fallback, values) => interpolate((key ? lookup(messages, key) : undefined) ?? fallback ?? key ?? "", values);
  t.locale = locale;
  return t;
}
