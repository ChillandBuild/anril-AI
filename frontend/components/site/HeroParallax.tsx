"use client";

import { useEffect } from "react";
import { loadScrollTrigger, prefersReducedMotion } from "./motion-lib";

/** Scroll-linked drift for the home hero: the photo moves slower than the page, the copy eases away. */
export function HeroParallax() {
  useEffect(() => {
    if (prefersReducedMotion()) return;
    let cancelled = false;
    let kill = () => {};
    (async () => {
      const { gsap } = await loadScrollTrigger();
      if (cancelled) return;
      const scene = document.querySelector("[data-hero-scene]");
      const copy = document.querySelector("[data-hero-copy]");
      const hero = document.querySelector("[data-hero]");
      if (!scene || !copy || !hero) return;
      const ctx = gsap.context(() => {
        const trigger = { trigger: hero, start: "top top", end: "bottom top", scrub: true };
        gsap.to(scene, { yPercent: 3, ease: "none", scrollTrigger: trigger });
        gsap.to(copy, { yPercent: -12, opacity: 0.2, ease: "none", scrollTrigger: trigger });
      });
      kill = () => ctx.revert();
    })();
    return () => {
      cancelled = true;
      kill();
    };
  }, []);
  return null;
}
