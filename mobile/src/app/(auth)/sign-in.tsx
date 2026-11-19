import { zodResolver } from '@hookform/resolvers/zod';
import { router } from 'expo-router';
import { Lock, Mail } from 'lucide-react-native';
import { useRef, useState, type ComponentRef } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { StyleSheet, TextInput, View } from 'react-native';

import { AppMark } from '@/components/app-mark';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/input';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { ApiError, errorMessage } from '@/lib/api';
import { closureFromResponse } from '@/lib/auth/account-status';
import { authApi, needsOtp } from '@/lib/auth/auth-api';
import { usePendingLogin } from '@/lib/auth/pending';
import { trustedDeviceToken, useSession } from '@/lib/auth/session';
import { haptic } from '@/lib/haptics';
import { normalizeEmail, signInSchema } from '@/lib/validation';
import { useTheme } from '@/theme/theme';
import { radius, space } from '@/theme/tokens';

type Values = { email: string; password: string };

/**
 * POST /login. A trusted device (device_token from an earlier code check) gets a session at once;
 * a new device gets a code challenge and goes to /verify. Staff accounts are refused with the
 * server's own `form` message (403 {mobileAccess: "staff_not_allowed"}).
 */
export default function SignIn() {
  const { c } = useTheme();
  const completeSignIn = useSession((s) => s.completeSignIn);
  const setPending = usePendingLogin((s) => s.set);
  const lastUser = useSession((s) => s.user);
  const passwordRef = useRef<ComponentRef<typeof TextInput>>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const { control, handleSubmit, setError, formState } = useForm<Values>({
    resolver: zodResolver(signInSchema),
    mode: 'onTouched',
    reValidateMode: 'onChange',
    defaultValues: { email: typeof lastUser?.email === 'string' ? lastUser.email : '', password: '' },
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    const email = normalizeEmail(values.email);
    try {
      const result = await authApi.login({ email, password: values.password, device_token: await trustedDeviceToken() });
      if (needsOtp(result)) {
        setPending({ email, challenge_token: result.challenge_token, resend_token: result.resend_token, channels: result.channels ?? [], resend_after: result.resend_after });
        router.push('/verify');
        return;
      }
      haptic.success();
      await completeSignIn(result, result.user, result.device_token);
    } catch (e) {
      haptic.error();
      const error = e instanceof ApiError ? e : null;
      const closure = error ? closureFromResponse(error.status, error.body) : null;
      if (closure) {
        await useSession.getState().closeAccount(closure);
        return;
      }
      if (error?.code !== 'staff_not_allowed' && error?.fields.email) setError('email', { message: error.fields.email });
      else if (error?.fields.password) setError('password', { message: error.fields.password });
      else if (error?.status === 429 && !error.message)
        setFormError(t('auth.signIn.tooMany', { minutes: Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60)) }));
      else setFormError(errorMessage(e));
    }
  });

  return (
    <Screen keyboard contentStyle={styles.content}>
      <View style={{ gap: space.xxl }}>
        <AppMark size={44} />
        <View style={{ gap: 6 }}>
          <Text variant="title" accessibilityRole="header">
            {t('auth.signIn.title')}
          </Text>
          <Text variant="callout" tone="muted">
            {t('auth.signIn.subtitle')}
          </Text>
        </View>
        <View style={{ gap: space.lg }}>
          <Controller
            control={control}
            name="email"
            render={({ field, fieldState }) => (
              <Field
                label={t('auth.signIn.email')}
                icon={Mail}
                value={field.value}
                onChangeText={(v) => field.onChange(v.replace(/\s/g, ''))}
                onBlur={field.onBlur}
                error={fieldState.error?.message ? t(fieldState.error.message) : null}
                placeholder={t('auth.signIn.emailPlaceholder')}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="email-address"
                textContentType="username"
                autoComplete="email"
                maxLength={254}
                returnKeyType="next"
                onSubmitEditing={() => passwordRef.current?.focus()}
              />
            )}
          />
          <Controller
            control={control}
            name="password"
            render={({ field, fieldState }) => (
              <Field
                ref={passwordRef}
                label={t('auth.signIn.password')}
                icon={Lock}
                secure
                value={field.value}
                onChangeText={field.onChange}
                onBlur={field.onBlur}
                error={fieldState.error?.message ? t(fieldState.error.message) : null}
                placeholder={t('auth.signIn.passwordPlaceholder')}
                textContentType="password"
                autoComplete="current-password"
                maxLength={120}
                returnKeyType="go"
                onSubmitEditing={() => void submit()}
              />
            )}
          />
          {formError ? (
            <View style={[styles.alert, { backgroundColor: c.negativeSurface }]} accessibilityLiveRegion="assertive">
              <Text variant="callout" tone="negative">
                {formError}
              </Text>
            </View>
          ) : null}
          <Button label={t('auth.signIn.submit')} onPress={() => void submit()} loading={formState.isSubmitting} disabled={!formState.isValid} />
        </View>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { paddingTop: space.xxxl * 1.5, paddingBottom: space.xxl },
  alert: { borderRadius: radius.md, padding: 14 },
});
