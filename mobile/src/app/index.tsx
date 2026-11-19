import { Redirect } from 'expo-router';

import { useClosure } from '@/lib/auth/closure';
import { useSession } from '@/lib/auth/session';

/** Entry point: every session state has exactly one place to be. */
export default function Index() {
  const status = useSession((s) => s.status);
  const closed = useClosure((s) => !!s.closure);
  if (status === 'signedOut' && closed) return <Redirect href="/account-closed" />;
  if (status === 'signedOut') return <Redirect href="/sign-in" />;
  if (status === 'setup') return <Redirect href="/create-pin" />;
  if (status === 'locked') return <Redirect href="/unlock" />;
  if (status === 'unlocked') return <Redirect href="/home" />;
  return null;
}
