import { create } from 'zustand';

/** In memory only: the one-time sign-in challenge between the password and code screens. */
type PendingFields = {
  email: string;
  challenge_token: string;
  resend_token?: string;
  channels: string[];
  resend_after?: number;
};

type Pending = PendingFields & {
  set: (p: PendingFields) => void;
  clear: () => void;
};

const empty: PendingFields = { email: '', challenge_token: '', resend_token: undefined, channels: [], resend_after: undefined };

export const usePendingLogin = create<Pending>((set) => ({
  ...empty,
  set: (p) => set(p),
  clear: () => set(empty),
}));
