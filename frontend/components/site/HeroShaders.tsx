"use client";

import { useEffect, useRef } from "react";
import s from "./HomeHero.module.css";
import { DITHER, MESH, TEAL_RGB, makeLayer, saveDataOn, whenIdle, type Layer } from "./shaderLayers";

// The animated background of the home hero: the drifting mesh and the teal halftone from shaderLayers.ts.
// The page paints first with a plain CSS gradient; the shaders start once the browser is idle, pause when the
// tab is hidden or the hero scrolls out of view, and stay still for visitors who ask for reduced motion.

/** The animated background of the home hero. Decorative only, so it is hidden from assistive tech. */
export function HeroShaders() {
  const meshRef = useRef<HTMLDivElement>(null);
  const ditherRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const meshHost = meshRef.current;
    const ditherHost = ditherRef.current;
    const hero = meshHost?.closest<HTMLElement>("[data-hero]");
    if (!meshHost || !ditherHost || !hero) return;
    // Phones on Save-Data keep the plain gradient.
    if (saveDataOn()) return;

    let cancelled = false;
    let raf = 0;
    let visible = true;
    let layers: Layer[] = [];
    let cleanup = () => {};

    const start = () => {
      if (cancelled) return;
      const mesh = makeLayer(meshHost, MESH, { className: s.glCanvas, scale: 0.5 });
      // Halftone squares are 3 CSS px, 2 on phones so the pattern stays fine on a small screen.
      const small = window.matchMedia("(max-width: 900px)").matches;
      const dither = makeLayer(ditherHost, DITHER, { className: s.glCanvas, scale: 1, pixel: small ? 2 : 3, color: TEAL_RGB });
      layers = [mesh, dither].filter((l): l is Layer => !!l);
      if (!layers.length) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      let meshT = 6;
      let ditherT = 4;
      let speed = 0.2;
      let target = 0.2;
      let prev = performance.now();
      let mx = 0;
      let my = 0;
      let tx = 0;
      let ty = 0;
      let last = -9999;

      const paint = () => {
        mesh?.draw(meshT);
        dither?.draw(ditherT);
        for (const l of layers) l.cv.dataset.on = "1";
      };
      paint();
      if (reduce) return;

      const move = (e: PointerEvent) => {
        const r = hero.getBoundingClientRect();
        tx = ((e.clientX - r.left) / r.width - 0.5) * 2;
        ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
        last = performance.now();
      };
      const over = () => (target = 0.6);
      const out = () => (target = 0.2);
      const hoverOk = window.matchMedia("(hover: hover)").matches;
      if (hoverOk) {
        hero.addEventListener("pointermove", move);
        hero.addEventListener("pointerenter", over);
        hero.addEventListener("pointerleave", out);
      }
      const io = new IntersectionObserver(([en]) => (visible = en.isIntersecting));
      io.observe(hero);

      const tick = (now: number) => {
        raf = requestAnimationFrame(tick);
        const dt = Math.min((now - prev) / 1000, 0.1);
        prev = now;
        if (document.hidden || !visible) return;
        if (now - last > 2200) {
          tx = Math.sin(now * 0.00028) * 0.8;
          ty = Math.cos(now * 0.0002) * 0.3;
        }
        mx += (tx - mx) * 0.05;
        my += (ty - my) * 0.05;
        hero.style.setProperty("--mx", mx.toFixed(4));
        hero.style.setProperty("--my", my.toFixed(4));
        speed += (target - speed) * 0.06;
        meshT += dt * 0.73;
        ditherT += dt * speed * 3;
        mesh?.draw(meshT);
        dither?.draw(ditherT);
      };
      raf = requestAnimationFrame(tick);
      cleanup = () => {
        io.disconnect();
        hero.removeEventListener("pointermove", move);
        hero.removeEventListener("pointerenter", over);
        hero.removeEventListener("pointerleave", out);
      };
    };

    // Wait for the first paint and an idle moment, so the shaders never compete with the headline.
    const cancelIdle = whenIdle(start);

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      cancelIdle();
      cleanup();
      layers.forEach((l) => l.lose());
    };
  }, []);

  return (
    <div className={s.gl} aria-hidden="true">
      <div ref={meshRef} className={s.glMesh} />
      <div ref={ditherRef} className={s.glDither} />
    </div>
  );
}
