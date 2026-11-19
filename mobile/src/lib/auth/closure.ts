import { create } from 'zustand';

import type { AccountClosure } from './account-status';

/**
 * State for the "account closed" screen (src/app/account-closed.tsx). Memory only: the device
 * is already wiped when this is set and the reason is never stored. Cleared by "Back to sign in".
 */
type ClosureState = {
  closure: AccountClosure | null;
  show: (closure: AccountClosure) => void;
  clear: () => void;
};

export const useClosure = create<ClosureState>((set) => ({
  closure: null,
  show: (closure) => set({ closure }),
  clear: () => set({ closure: null }),
}));
