import { router } from 'expo-router';
import { usePreventScreenCapture } from 'expo-screen-capture';
import { ChevronLeft, ShieldCheck } from 'lucide-react-native';
import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';

import { Button } from '@/components/ui/button';
import { IconBadge } from '@/components/ui/card';
import { CodeInput } from '@/components/ui/code-input';
import { Screen } from '@/components/ui/screen';
import { Text } from '@/components/ui/text';
import { t } from '@/i18n';
import { ApiError, errorMessage } from '@/lib/api';
import { closureFromResponse } from '@/lib/auth/account-status';
import { authApi } from '@/lib/auth/auth-api';
import { usePendingLogin } from '@/lib/auth/pending';
import { useSession } from '@/lib/auth/session';
import { haptic } from '@/lib/haptics';
import { useTheme } from '@/theme/theme';
import { space } from '@/theme/tokens';

const CODE_LENGTH = 6;

/** New device: POST /verify-login with the emailed (or SMS) code; POST /resend-login for a new one. */
export default function VerifySignIn() {
  usePreventScreenCapture();
  const { c } = useTheme();
  const pending = usePendingLogin();
  const completeSignIn = useSession((s) => s.completeSignIn);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(pending.resend_after ?? 60);

  useEffect(() => {
    if (!pending.challenge_token) router.replace('/sign-in');
  }, [pending.challenge_token]);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  async function verify(value = code) {
    if (value.length !== CODE_LENGTH || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await authApi.verifyLogin({ challenge_token: pending.challenge_token, code: value });
      haptic.success();
      pending.clear();
      await completeSignIn(result, result.user, result.device_token);
    } catch (e) {
      haptic.error();
      const err = e instanceof ApiError ? e : null;
      const closure = err ? closureFromResponse(err.status, err.body) : null;
      if (closure) {
        pending.clear();
        await useSession.getState().closeAccount(closure);
        return;
      }
      setError(err?.fields.code ?? errorMessage(e));
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (!pending.resend_token) return;
    try {
      const r = await authApi.resendLogin({ resend_token: pending.resend_token });
      pending.set({
        email: pending.email,
        challenge_token: r.challenge_token,
        resend_token: r.resend_token ?? pending.resend_token,
        channels: r.channels ?? pending.channels,
        resend_after: r.resend_after,
      });
      setWait(r.resend_after ?? 60);
      setError(null);
      haptic.success();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const channel = pending.channels.includes('sms') ? t('verify.channelEmailPhone') : t('verify.channelEmail');

  return (
    <Screen keyboard footer={<Button label={t('verify.submit')} onPress={() => void verify()} loading={busy} disabled={code.length !== CODE_LENGTH} />}>
      <Pressable onPress={() => router.back()} accessibilityRole="button" accessibilityLabel={t('common.back')} hitSlop={12} style={{ marginTop: space.sm, marginLeft: -6 }}>
        <ChevronLeft size={28} color={c.text} />
      </Pressable>
      <View style={{ gap: space.xl, marginTop: space.xl }}>
        <IconBadge icon={ShieldCheck} size={56} />
        <View style={{ gap: 6 }}>
          <Text variant="title" accessibilityRole="header">
            {t('verify.title')}
          </Text>
          <Text variant="callout" tone="muted">
            {t('verify.body', { channel, email: pending.email })}
          </Text>
        </View>
        <CodeInput
          value={code}
          length={CODE_LENGTH}
          error={!!error}
          onChange={(v) => {
            setCode(v);
            setError(null);
            if (v.length === CODE_LENGTH) void verify(v);
          }}
        />
        {error ? (
          <Text variant="callout" tone="negative" align="center" accessibilityLiveRegion="assertive">
            {error}
          </Text>
        ) : null}
        <Pressable disabled={wait > 0} onPress={() => void resend()} accessibilityRole="button" style={{ alignSelf: 'center', padding: space.sm }}>
          <Text variant="callout" tone={wait > 0 ? 'subtle' : 'primary'}>
            {wait > 0 ? t('verify.resendIn', { seconds: wait }) : t('verify.resend')}
          </Text>
        </Pressable>
      </View>
    </Screen>
  );
}
