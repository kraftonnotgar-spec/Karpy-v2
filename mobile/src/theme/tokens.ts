/**
 * Design tokens: the ONLY file in the app that may contain colour literals.
 *
 * Light and dark are two designed palettes, not inversions. To brand a project, change
 * `brand` and the two palettes below; everything else (screens, components, the native splash,
 * the Android adaptive icon background and the notification accent via app.config.ts) reads
 * from here.
 *
 * Kept free of React Native imports so app.config.ts and node tests can import it.
 */

export const brand = {
  /** Main brand colour (buttons, links, accents). */
  primary: '#3B5BDB',
  primaryDeep: '#2B44A8',
  /** Brand colour tuned for dark backgrounds. */
  primaryOnDark: '#8EA6FF',
  /** Native splash / launcher backgrounds. */
  splashLight: '#F5F6F8',
  splashDark: '#101216',
} as const;

export type Palette = {
  page: string;
  surface: string;
  surfaceRaised: string;
  surfaceSunken: string;
  border: string;
  borderStrong: string;
  text: string;
  textMuted: string;
  textSubtle: string;
  primary: string;
  primaryText: string;
  primaryPressed: string;
  accent: string;
  accentSurface: string;
  positive: string;
  positiveSurface: string;
  pending: string;
  pendingSurface: string;
  negative: string;
  negativeSurface: string;
  info: string;
  infoSurface: string;
  overlay: string;
  shadow: string;
  /** Fully transparent fill (ghost buttons, spacer keys). */
  transparent: string;
};

export const light: Palette = {
  page: brand.splashLight,
  surface: '#FFFFFF',
  surfaceRaised: '#FFFFFF',
  surfaceSunken: '#ECEEF2',
  border: '#E1E4EA',
  borderStrong: '#C9CED8',
  text: '#11141A',
  textMuted: '#5B6271',
  textSubtle: '#8A90A0',
  primary: brand.primary,
  primaryText: '#FFFFFF',
  primaryPressed: brand.primaryDeep,
  accent: brand.primary,
  accentSurface: '#E8EDFF',
  positive: '#1F7A44',
  positiveSurface: '#E3F3E9',
  pending: '#8F6300',
  pendingSurface: '#FBF0D6',
  negative: '#C2343A',
  negativeSurface: '#FCE8E8',
  info: '#2C6CB0',
  infoSurface: '#E5EEF8',
  overlay: 'rgba(10, 12, 18, 0.45)',
  shadow: '#0B1020',
  transparent: 'transparent',
};

export const dark: Palette = {
  page: brand.splashDark,
  surface: '#181B21',
  surfaceRaised: '#1F232A',
  surfaceSunken: '#14161B',
  border: '#272B33',
  borderStrong: '#363B45',
  text: '#F1F3F7',
  textMuted: '#A5ABB8',
  textSubtle: '#777E8C',
  primary: brand.primaryOnDark,
  primaryText: '#0B1020',
  primaryPressed: '#7590F5',
  accent: brand.primaryOnDark,
  accentSurface: 'rgba(142, 166, 255, 0.14)',
  positive: '#6FD08A',
  positiveSurface: 'rgba(111, 208, 138, 0.12)',
  pending: '#E8C15A',
  pendingSurface: 'rgba(232, 193, 90, 0.12)',
  negative: '#FF8A8C',
  negativeSurface: 'rgba(255, 138, 140, 0.12)',
  info: '#86B6F0',
  infoSurface: 'rgba(134, 182, 240, 0.12)',
  overlay: 'rgba(0, 0, 0, 0.6)',
  shadow: '#000000',
  transparent: 'transparent',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, xxxl: 32 } as const;
export const radius = { sm: 10, md: 14, lg: 18, xl: 24, pill: 999 } as const;

/** System font with weights; load a font with expo-font and add `fontFamily` here to brand the type. */
export const weight = { regular: '400', medium: '500', semibold: '600', bold: '700' } as const;

export const type = {
  display: { fontSize: 34, lineHeight: 40, fontWeight: weight.semibold, letterSpacing: -0.6 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: weight.semibold, letterSpacing: -0.4 },
  headline: { fontSize: 20, lineHeight: 26, fontWeight: weight.semibold, letterSpacing: -0.2 },
  subhead: { fontSize: 17, lineHeight: 22, fontWeight: weight.semibold },
  body: { fontSize: 16, lineHeight: 22, fontWeight: weight.regular },
  bodyStrong: { fontSize: 16, lineHeight: 22, fontWeight: weight.medium },
  callout: { fontSize: 15, lineHeight: 20, fontWeight: weight.regular },
  footnote: { fontSize: 13, lineHeight: 18, fontWeight: weight.regular },
  caption: { fontSize: 12, lineHeight: 16, fontWeight: weight.medium },
  overline: { fontSize: 12, lineHeight: 16, fontWeight: weight.semibold, letterSpacing: 0.6 },
} as const;

export type TypeVariant = keyof typeof type;
