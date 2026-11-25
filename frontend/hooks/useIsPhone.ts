"use client";
import { useEffect, useState } from "react";

/** Below Tailwind's `lg` (1024px): the phone / PWA layout with the bottom bar. */
export const PHONE_QUERY = "(max-width: 1023.98px)";

/**
 * True on the phone layout. Starts false (server render and first paint), then follows the
 * screen width. Use it to MOUNT phone-only parts that fetch, poll or lock scroll, so they never
 * run on desktop; plain look-only differences stay as CSS (`lg:hidden`).
 */
export function useIsPhone(): boolean {
  const [isPhone, setIsPhone] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY);
    const update = () => setIsPhone(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return isPhone;
}
