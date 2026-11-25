"use client";

import { Toaster } from "sonner";
import { useIsPhone } from "@/hooks/useIsPhone";

/** Above the phone bottom bar, so toasts never cover the header's buttons or the bar itself. */
const ABOVE_BOTTOM_BAR = { bottom: "calc(var(--mobile-nav-h) + env(safe-area-inset-bottom, 0px) + 12px)" };

/**
 * App-wide toasts. Desktop keeps them top-right. On the phone layout (below lg, where the bottom
 * bar shows) they sit bottom-center just above the bar, clear of the header's Back, Call, bell and
 * profile buttons.
 */
export function AppToaster() {
  const isPhone = useIsPhone();
  return isPhone ? (
    <Toaster position="bottom-center" offset={ABOVE_BOTTOM_BAR} mobileOffset={ABOVE_BOTTOM_BAR} richColors closeButton />
  ) : (
    <Toaster position="top-right" richColors closeButton />
  );
}
