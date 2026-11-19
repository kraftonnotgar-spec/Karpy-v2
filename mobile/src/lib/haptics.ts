import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';

/** One vocabulary of touch feedback: tap, soft, confirm, success, warning, error. */
const native = Platform.OS === 'ios' || Platform.OS === 'android';

function safe(fn: () => Promise<void>) {
  if (!native) return;
  fn().catch(() => {});
}

export const haptic = {
  tap: () => safe(() => Haptics.selectionAsync()),
  soft: () => safe(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Soft)),
  confirm: () => safe(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium)),
  success: () => safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)),
  warning: () => safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning)),
  error: () => safe(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error)),
};
