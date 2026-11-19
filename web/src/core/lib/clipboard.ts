/** How long a "Copied" confirmation stays visible. */
export const COPY_FEEDBACK_MS = 1500;

/**
 * Copies text with the async Clipboard API, falling back to a hidden textarea +
 * execCommand("copy") on non-secure origins (http LAN previews), older WebViews
 * or when the permission is denied. Resolves false instead of throwing.
 */
export async function copyText(value: string): Promise<boolean> {
  if (typeof window === "undefined" || !value) return false;
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall through to the legacy path (focus loss, denied permission).
  }
  return legacyCopy(value);
}

function legacyCopy(value: string) {
  const doc = window.document;
  if (!doc?.body || typeof doc.execCommand !== "function") return false;
  const active = doc.activeElement as HTMLElement | null;
  const area = doc.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.setAttribute("aria-hidden", "true");
  // Off-screen but selectable; 16px avoids iOS zoom on focus.
  area.style.cssText = "position:fixed;top:0;left:-9999px;opacity:0;font-size:16px";
  doc.body.appendChild(area);
  try {
    area.select();
    area.setSelectionRange(0, value.length);
    return doc.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
    active?.focus?.({ preventScroll: true });
  }
}
