import * as LocalAuthentication from 'expo-local-authentication';
import { Platform } from 'react-native';

import { t } from '@/i18n';
import { getJSON, keys, setJSON } from '@/lib/storage';

/**
 * What the OS prompt will use. iOS reports exactly one of Face ID / Touch ID. Android's
 * BiometricPrompt picks the modality itself, so it is "fingerprint" whenever a fingerprint
 * sensor exists, "face" only when face is the only kind, otherwise "biometrics".
 */
export type BiometricKind = 'face' | 'fingerprint' | 'iris' | 'biometrics' | null;

export function kindFor(os: string, types: LocalAuthentication.AuthenticationType[]): BiometricKind {
  const T = LocalAuthentication.AuthenticationType;
  if (!types.length) return null;
  if (os === 'ios') {
    if (types.includes(T.FACIAL_RECOGNITION)) return 'face';
    if (types.includes(T.FINGERPRINT)) return 'fingerprint';
    return 'biometrics';
  }
  if (types.includes(T.FINGERPRINT)) return 'fingerprint';
  if (types.every((x) => x === T.FACIAL_RECOGNITION)) return 'face';
  return 'biometrics';
}

/** What the device can do right now (hardware present AND something enrolled). */
export async function biometricKind(): Promise<BiometricKind> {
  if (Platform.OS === 'web') return null;
  const [hardware, enrolled] = await Promise.all([LocalAuthentication.hasHardwareAsync(), LocalAuthentication.isEnrolledAsync()]);
  if (!hardware || !enrolled) return null;
  return kindFor(Platform.OS, await LocalAuthentication.supportedAuthenticationTypesAsync());
}

export function biometricLabel(kind: BiometricKind) {
  const ios = Platform.OS === 'ios';
  if (kind === 'face') return t(ios ? 'biometrics.faceId' : 'biometrics.face');
  if (kind === 'fingerprint') return t(ios ? 'biometrics.touchId' : 'biometrics.fingerprint');
  return t('biometrics.generic');
}

export async function biometricsEnabled() {
  return (await getJSON<boolean>(keys.biometrics)) === true;
}

export function setBiometricsEnabled(value: boolean) {
  return setJSON(keys.biometrics, value);
}

/**
 * The operating system's own prompt. The device passcode fallback is disabled: the app PIN is
 * the fallback, so a phone passcode alone never opens the app.
 */
export async function promptBiometrics(reason: string = t('unlock.biometricPrompt')) {
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: reason,
    cancelLabel: t('unlock.usePin'),
    disableDeviceFallback: true,
    fallbackLabel: '',
    biometricsSecurityLevel: 'strong',
  });
  return result.success;
}
