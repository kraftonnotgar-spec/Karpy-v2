import { useRef, type ComponentRef } from 'react';
import { Platform, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { t } from '@/i18n';
import { useTheme } from '@/theme/theme';
import { type as ramp } from '@/theme/tokens';
import { Text } from './text';

/** Digits from whatever arrived (typed, pasted sentence, OS autofill). */
export function codeFromInput(text: string, length: number) {
  const run = new RegExp(`(?<!\\d)\\d{${length}}(?!\\d)`).exec(text)?.[0];
  return run ?? text.replace(/\D/g, '').slice(0, length);
}

/**
 * One hidden input behind N boxes, so the system can fill the whole code at once (iOS
 * oneTimeCode, Android sms-otp suggestions).
 */
export function CodeInput({ value, onChange, length = 6, error, autoFocus = true }: { value: string; onChange: (v: string) => void; length?: number; error?: boolean; autoFocus?: boolean }) {
  const { c } = useTheme();
  const ref = useRef<ComponentRef<typeof TextInput>>(null);
  return (
    <Pressable onPress={() => ref.current?.focus()} accessibilityLabel={t('verify.codeLabel')} style={styles.wrap}>
      <TextInput
        ref={ref}
        value={value}
        onChangeText={(text) => onChange(codeFromInput(text, length))}
        keyboardType="number-pad"
        textContentType="oneTimeCode"
        autoComplete={Platform.OS === 'android' ? 'sms-otp' : 'one-time-code'}
        autoFocus={autoFocus}
        maxLength={64}
        caretHidden
        style={styles.hidden}
      />
      {Array.from({ length }, (_, i) => {
        const active = i === Math.min(value.length, length - 1);
        return (
          <View key={i} style={[styles.cell, { backgroundColor: c.surface, borderColor: error ? c.negative : active ? c.accent : c.border }, active && { borderWidth: 1.5 }]}>
            <Text style={[ramp.headline, { color: c.text }]}>{value[i] ?? ''}</Text>
          </View>
        );
      })}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row', gap: 8, justifyContent: 'center' },
  hidden: { position: 'absolute', opacity: 0, width: 1, height: 1 },
  cell: { width: 48, height: 58, borderRadius: 14, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
});
