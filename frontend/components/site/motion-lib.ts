// Shared helpers for the /new site's scroll motion. GSAP and Lenis are loaded on demand so the
// pages that never scroll-scrub do not pay for them, and nothing loads at all under reduced motion.

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export async function loadScrollTrigger() {
  const [{ default: gsap }, { ScrollTrigger }] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
  gsap.registerPlugin(ScrollTrigger);
  return { gsap, ScrollTrigger };
}
