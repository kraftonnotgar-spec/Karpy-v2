"use client";

import { createContext, useContext, useMemo } from "react";
import { createTranslator, type MessageTree, type Translator } from "./index";

const I18nContext = createContext<Translator | null>(null);

/** Mounted once in the root layout with the active locale's merged catalog. */
export function I18nProvider({ locale, messages, children }: { locale: string; messages: MessageTree; children: React.ReactNode }) {
  const t = useMemo(() => createTranslator(messages, locale), [messages, locale]);
  return <I18nContext.Provider value={t}>{children}</I18nContext.Provider>;
}

/** Client components translate with this: `const t = useT(); t("common.signIn")`. */
export function useT(): Translator {
  const t = useContext(I18nContext);
  if (!t) throw new Error("useT() needs <I18nProvider> (mounted in src/app/layout.tsx).");
  return t;
}
