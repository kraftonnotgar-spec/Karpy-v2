import * as Crypto from 'expo-crypto';
import * as Device from 'expo-device';

import { config } from './config';
import { getOrCreateDeviceId } from './device-id';
import { getItem, keys, setItem } from './storage';

let pending: Promise<string> | null = null;

/** This installation's id (created once, kept in secure storage). Concurrent callers share one read. */
export function deviceId(): Promise<string> {
  pending ??= getOrCreateDeviceId({ getItem, setItem }, keys.deviceId, (n) => Crypto.getRandomBytes(n)).catch((error) => {
    pending = null;
    throw error;
  });
  return pending;
}

/** The device fields every sign-in call carries. */
export async function deviceFields() {
  return {
    device_id: await deviceId(),
    device_name: (Device.deviceName ?? Device.modelName ?? (config.platform === 'ios' ? 'iPhone' : 'Android')).slice(0, 80),
    platform: config.platform === 'android' ? ('android' as const) : ('ios' as const),
  };
}
