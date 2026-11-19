import { Text as RNText, type TextProps, type TextStyle } from 'react-native';

import { useTheme } from '@/theme/theme';
import { type as ramp, type TypeVariant } from '@/theme/tokens';

export type Tone = 'default' | 'muted' | 'subtle' | 'primary' | 'positive' | 'negative' | 'pending' | 'inverse';

export type AppTextProps = TextProps & {
  variant?: TypeVariant;
  tone?: Tone;
  align?: TextStyle['textAlign'];
};

export function Text({ variant = 'body', tone = 'default', align, style, maxFontSizeMultiplier = 1.6, ...rest }: AppTextProps) {
  const { c } = useTheme();
  const color = {
    default: c.text,
    muted: c.textMuted,
    subtle: c.textSubtle,
    primary: c.accent,
    positive: c.positive,
    negative: c.negative,
    pending: c.pending,
    inverse: c.primaryText,
  }[tone];
  return <RNText maxFontSizeMultiplier={maxFontSizeMultiplier} style={[ramp[variant], { color, textAlign: align }, style]} {...rest} />;
}
