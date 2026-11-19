import { Pressable as RNPressable, type PressableProps, type StyleProp, type ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring, withTiming } from 'react-native-reanimated';

import { haptic } from '@/lib/haptics';

const AnimatedPressable = Animated.createAnimatedComponent(RNPressable);

export type ScalePressableProps = Omit<PressableProps, 'style'> & {
  style?: StyleProp<ViewStyle>;
  scaleTo?: number;
  feedback?: 'tap' | 'soft' | 'none';
};

/** Press-in shrink with a spring release and a haptic tick. */
export function ScalePressable({ style, scaleTo = 0.97, feedback = 'tap', onPressIn, onPressOut, onPress, disabled, ...rest }: ScalePressableProps) {
  const scale = useSharedValue(1);
  const animated = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  return (
    <AnimatedPressable
      accessibilityRole="button"
      disabled={disabled}
      onPressIn={(e) => {
        scale.set(withTiming(scaleTo, { duration: 90 }));
        onPressIn?.(e);
      }}
      onPressOut={(e) => {
        scale.set(withSpring(1, { damping: 14, stiffness: 260 }));
        onPressOut?.(e);
      }}
      onPress={(e) => {
        if (feedback !== 'none') haptic[feedback]();
        onPress?.(e);
      }}
      style={[animated, style, disabled && { opacity: 0.5 }]}
      {...rest}
    />
  );
}
