import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Platform, useColorScheme, type ViewStyle } from 'react-native';
import { create } from 'zustand';

import { getItem, keys, setItem } from '@/lib/storage';
import { dark, light, type Palette } from './tokens';

export type ThemePreference = 'system' | 'light' | 'dark';

type ThemeStore = {
  preference: ThemePreference;
  setPreference: (value: ThemePreference) => void;
  hydrate: () => Promise<void>;
};

export const useThemeStore = create<ThemeStore>((set) => ({
  preference: 'system',
  setPreference: (preference) => {
    set({ preference });
    void setItem(keys.theme, preference);
  },
  hydrate: async () => {
    const stored = await getItem(keys.theme);
    set({ preference: stored === 'light' || stored === 'dark' ? stored : 'system' });
  },
}));

type Theme = { scheme: 'light' | 'dark'; c: Palette };

const ThemeContext = createContext<Theme>({ scheme: 'light', c: light });

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme();
  const preference = useThemeStore((s) => s.preference);
  const hydrate = useThemeStore((s) => s.hydrate);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void hydrate().finally(() => setReady(true));
  }, [hydrate]);

  const scheme: 'light' | 'dark' = preference === 'system' ? (system === 'dark' ? 'dark' : 'light') : preference;
  const value = useMemo(() => ({ scheme, c: scheme === 'dark' ? dark : light }), [scheme]);
  if (!ready) return null;
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

/** Soft card shadow on iOS light mode, elevation on Android, nothing in dark mode. */
export function shadow(scheme: 'light' | 'dark', c: Palette): ViewStyle {
  if (scheme === 'dark') return {};
  return (
    Platform.select<ViewStyle>({
      ios: { shadowColor: c.shadow, shadowOpacity: 0.06, shadowRadius: 12, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 1 },
      default: {},
    }) ?? {}
  );
}
