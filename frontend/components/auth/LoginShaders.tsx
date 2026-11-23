"use client";

import { useEffect, useRef } from "react";
import {
  DITHER,
  MESH,
  TEAL_LIGHT_RGB,
  TEAL_RGB,
  makeLayer,
  saveDataOn,
  whenIdle,
  type Layer,
} from "@/components/site/shaderLayers";
import s from "./login.module.css";

/**
 * The home hero's moving background, for the login page.
 *   light: the drifting white and teal mesh plus the teal halftone, behind the sign-in card.
 *   navy:  the halftone alone in light teal, on the navy panel.
 * Same rules as the home hero: starts once the browser is idle, pauses when the tab is hidden or the
 * layer is off screen, speeds up a little while the pointer is over it, holds one still frame for
 * visitors who ask for reduced motion, and stays off on Save-Data. Decorative, so hidden from assistive tech.
 */
export function LoginShaders({ variant }: { variant: "light" | "navy" }) {
  const meshRef = useRef<HTMLDivElement>(null);
  const ditherRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ditherHost = ditherRef.current;
    const area = ditherHost?.parentElement?.parentElement;
    if (!ditherHost || !area || saveDataOn()) return;

    let cancelled = false;
    let raf = 0;
    let visible = true;
    let layers: Layer[] = [];
    let cleanup = () => {};

    const start = () => {
      if (cancelled) return;
      const small = window.matchMedia("(max-width: 900px)").matches;
      const mesh = variant === "light" && meshRef.current ? makeLayer(meshRef.current, MESH, { className: s.glCanvas, scale: 0.5 }) : null;
      const dither = makeLayer(ditherHost, DITHER, {
        className: s.glCanvas,
        scale: 1,
        pixel: small ? 2 : 3,
        color: variant === "light" ? TEAL_RGB : TEAL_LIGHT_RGB,
      });
      layers = [mesh, dither].filter((l): l is Layer => !!l);
      if (!layers.length) return;

      let meshT = 6;
      let ditherT = variant === "light" ? 4 : 11;
      let speed = 0.2;
      let target = 0.2;
      let prev = performance.now();
      const paint = () => {
        mesh?.draw(meshT);
        dither?.draw(ditherT);
        for (const l of layers) l.cv.dataset.on = "1";
      };
      paint();
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const over = () => (target = 0.6);
      const out = () => (target = 0.2);
      area.addEventListener("pointerenter", over);
      area.addEventListener("pointerleave", out);
      const io = new IntersectionObserver(([en]) => (visible = en.isIntersecting));
      io.observe(area);

      const tick = (now: number) => {
        raf = requestAnimationFrame(tick);
        const dt = Math.min((now - prev) / 1000, 0.1);
        prev = now;
        if (document.hidden || !visible) return;
        speed += (target - speed) * 0.06;
        meshT += dt * 0.73;
        ditherT += dt * speed * 3;
        mesh?.draw(meshT);
        dither?.draw(ditherT);
      };
      raf = requestAnimationFrame(tick);
      cleanup = () => {
        io.disconnect();
        area.removeEventListener("pointerenter", over);
        area.removeEventListener("pointerleave", out);
      };
    };

    const cancelIdle = whenIdle(start);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      cancelIdle();
      cleanup();
      layers.forEach((l) => l.lose());
    };
  }, [variant]);

  return (
    <div className={`${s.gl} ${variant === "light" ? s.glLight : s.glNavy}`} aria-hidden="true">
      {variant === "light" && <div ref={meshRef} className={s.glMesh} />}
      <div ref={ditherRef} className={s.glDither} />
    </div>
  );
}
