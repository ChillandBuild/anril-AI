"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { loadScrollTrigger, prefersReducedMotion } from "./motion-lib";

/** Smooth scroll for the whole /new site, plus the fade-and-rise reveal for every `data-reveal` element. */
export function Motion() {
  const pathname = usePathname();

  useEffect(() => {
    if (prefersReducedMotion()) return;
    let cancelled = false;
    let cleanup = () => {};
    (async () => {
      const [{ gsap, ScrollTrigger }, { default: Lenis }] = await Promise.all([loadScrollTrigger(), import("lenis")]);
      if (cancelled) return;
      // Anchored sections clear the fixed header (see scroll-margin-top in site.module.css).
      const lenis = new Lenis({ lerp: 0.1, anchors: { offset: -96 } });
      lenis.on("scroll", ScrollTrigger.update);
      const tick = (t: number) => lenis.raf(t * 1000);
      gsap.ticker.add(tick);
      gsap.ticker.lagSmoothing(0);
      // The mobile menu locks page scroll with overflow:hidden; smooth scroll must stand down too.
      const html = document.documentElement;
      let locked = html.style.overflow === "hidden";
      const lock = new MutationObserver(() => {
        const now = html.style.overflow === "hidden";
        if (now === locked) return;
        locked = now;
        if (now) lenis.stop();
        else lenis.start();
      });
      lock.observe(html, { attributes: true, attributeFilter: ["style"] });
      cleanup = () => {
        lock.disconnect();
        gsap.ticker.remove(tick);
        lenis.destroy();
      };
    })();
    return () => {
      cancelled = true;
      cleanup();
    };
  }, []);

  useEffect(() => {
    const site = document.querySelector<HTMLElement>("[data-site]");
    if (!site) return;
    if (site.dataset.motion !== "on") return;
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          (e.target as HTMLElement).dataset.in = "";
          io.unobserve(e.target);
        }),
      { rootMargin: "0px 0px -8% 0px", threshold: 0.1 },
    );
    document.querySelectorAll<HTMLElement>("[data-reveal]:not([data-in])").forEach((el) => io.observe(el));
    site.dataset.motionReady = "";
    return () => io.disconnect();
  }, [pathname]);

  return null;
}
