import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, RefreshControl, ScrollView, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { useTheme } from '@/theme/theme';
import { space } from '@/theme/tokens';

type Props = {
  children: ReactNode;
  scroll?: boolean;
  edges?: Edge[];
  refreshing?: boolean;
  onRefresh?: () => void;
  contentStyle?: StyleProp<ViewStyle>;
  footer?: ReactNode;
  keyboard?: boolean;
};

/** Page scaffold: page background, safe areas, optional pull-to-refresh and a pinned footer. */
export function Screen({ children, scroll = true, edges = ['top'], refreshing, onRefresh, contentStyle, footer, keyboard }: Props) {
  const { c } = useTheme();
  const body = scroll ? (
    <ScrollView
      contentInsetAdjustmentBehavior="automatic"
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="interactive"
      showsVerticalScrollIndicator={false}
      contentContainerStyle={[styles.content, contentStyle]}
      refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={c.textMuted} colors={[c.accent]} /> : undefined}>
      {children}
    </ScrollView>
  ) : (
    <View style={[{ flex: 1 }, contentStyle]}>{children}</View>
  );
  const inner = (
    <>
      {body}
      {footer ? <View style={[styles.footer, { backgroundColor: c.page }]}>{footer}</View> : null}
    </>
  );
  return (
    <SafeAreaView edges={edges} style={{ flex: 1, backgroundColor: c.page }}>
      {keyboard ? (
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          {inner}
        </KeyboardAvoidingView>
      ) : (
        inner
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: space.lg, paddingBottom: space.xxxl },
  footer: { paddingHorizontal: space.lg, paddingTop: space.md, paddingBottom: space.lg },
});
