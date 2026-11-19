import Constants from 'expo-constants';

import en from './en.json';
import { createTranslator, hasKey, type Catalog, type Params } from './translate';

/**
 * Every user-facing string lives in a catalog (start: en.json). To add a language, add
 * `<locale>.json` with the same keys and put it before `en` in `catalogs` (pick it from
 * expo-localization when you add that package). `{app}` is always the configured app name.
 */
const catalogs: Catalog[] = [en as Catalog];
const appName = Constants.expoConfig?.name ?? 'App';
const translate = createTranslator(catalogs);

export function t(key: string, params?: Params): string {
  return translate(key, { app: appName, ...params });
}

export function tHas(key: string) {
  return hasKey(catalogs, key);
}
