"use client";

import { useEffect, useRef } from "react";
import s from "./HomeHero.module.css";

// Two small WebGL1 shaders behind the home hero, no libraries: a drifting white and teal mesh, and a teal
// halftone dither (a warped noise field cut into hard pixels by a 4x4 Bayer matrix). The page paints first
// with a plain CSS gradient; the shaders start once the browser is idle, pause when the tab is hidden or the
// hero scrolls out of view, and stay still for visitors who ask for reduced motion.

const VERT = "attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }";

// Mesh drift: soft blobs that wander around the screen, mixed through the palette.
const MESH = `
precision mediump float;
uniform vec2 u_res; uniform float u_time;
float gh(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec3 pal(int i){
  if (i == 0) return vec3(0.957, 0.969, 0.973);
  if (i == 1) return vec3(1.0);
  if (i == 2) return vec3(0.76, 0.90, 0.91);
  return vec3(0.87, 0.91, 0.93);
}
void main(){
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / min(u_res.x, u_res.y) * 1.16;
  vec3 acc = pal(0) * 0.15; float total = 0.15;
  for (int i = 0; i < 4; i++) {
    float fi = float(i);
    vec2 c = vec2(sin(u_time * (0.21 + fi * 0.071) + fi * 2.4 + 6.0), cos(u_time * (0.17 + fi * 0.093) + fi * 1.7)) * 0.57;
    float w = exp(-dot(p - c, p - c) * 6.0);
    acc += pal(i) * w; total += w;
  }
  vec3 col = acc / total;
  col += (gh(gl_FragCoord.xy) - 0.5) * 0.04;
  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}`;

// Halftone dither in Anril teal.
const DITHER = `
precision mediump float;
uniform vec2 u_res; uniform float u_time; uniform float u_px;
float h(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1.0, 0.0)), u.x), mix(h(i + vec2(0.0, 1.0)), h(i + vec2(1.0, 1.0)), u.x), u.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { v += a * n(p); p = p * 2.02 + 7.3; a *= 0.5; } return v; }
float b2(vec2 a){ a = floor(a); return fract(a.x / 2.0 + a.y * a.y * 0.75); }
float b4(vec2 a){ return b2(0.5 * a) * 0.25 + b2(a); }
void main(){
  vec2 cell = floor(gl_FragCoord.xy / u_px);
  vec2 p = (cell * u_px - 0.5 * u_res) / min(u_res.x, u_res.y);
  float t = u_time;
  vec2 q = vec2(fbm(p * 1.6 + vec2(0.0, t * 0.35)), fbm(p * 1.6 + vec2(5.2, 1.3) - t * 0.28));
  vec2 w = p + 0.9 * (q - 0.5) * 2.0;
  float v = 0.5 + 0.5 * sin(w.x * 3.2 + w.y * 2.4 + t * 0.9 + 3.0 * (q.x - q.y));
  v = smoothstep(0.15, 0.95, v);
  v *= 0.35 + 0.65 * smoothstep(1.35, 0.1, length(p * vec2(0.8, 1.2)));
  float on = step(b4(cell), v);
  gl_FragColor = vec4(vec3(0.012, 0.51, 0.52) * on, on);
}`;

type Layer = { gl: WebGLRenderingContext; cv: HTMLCanvasElement; uTime: WebGLUniformLocation | null; draw: (t: number) => void; lose: () => void };

function makeLayer(host: HTMLElement, frag: string, scale: number, pixel?: number): Layer | null {
  const cv = document.createElement("canvas");
  cv.className = s.glCanvas;
  const gl = cv.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: "low-power" });
  if (!gl) return null;
  const mk = (type: number, src: string) => {
    const sh = gl.createShader(type)!;
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    return sh;
  };
  const pr = gl.createProgram()!;
  gl.attachShader(pr, mk(gl.VERTEX_SHADER, VERT));
  gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, frag));
  gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return null;
  gl.useProgram(pr);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, "a");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.clearColor(0, 0, 0, 0);
  const uRes = gl.getUniformLocation(pr, "u_res");
  const uTime = gl.getUniformLocation(pr, "u_time");
  const uPx = gl.getUniformLocation(pr, "u_px");

  const dpr = Math.min(window.devicePixelRatio || 1, pixel ? 1.5 : 2);
  const size = () => {
    const w = Math.max(1, Math.round(host.clientWidth * dpr * scale));
    const h = Math.max(1, Math.round(host.clientHeight * dpr * scale));
    if (cv.width !== w || cv.height !== h) {
      cv.width = w;
      cv.height = h;
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uRes, w, h);
      if (uPx && pixel) gl.uniform1f(uPx, pixel * dpr * scale);
    }
  };
  host.appendChild(cv);
  size();
  const ro = new ResizeObserver(size);
  ro.observe(host);
  return {
    gl,
    cv,
    uTime,
    draw: (t: number) => {
      gl.useProgram(pr);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(uTime, t);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
    lose: () => {
      ro.disconnect();
      cv.remove();
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    },
  };
}

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
    const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (conn?.saveData) return;

    let cancelled = false;
    let raf = 0;
    let visible = true;
    let layers: Layer[] = [];
    let cleanup = () => {};

    const start = () => {
      if (cancelled) return;
      const mesh = makeLayer(meshHost, MESH, 0.5);
      // Halftone squares are 3 CSS px, 2 on phones so the pattern stays fine on a small screen.
      const small = window.matchMedia("(max-width: 900px)").matches;
      const dither = makeLayer(ditherHost, DITHER, 1, small ? 2 : 3);
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
    const w = window as Window & {
      requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number;
      cancelIdleCallback?: (h: number) => void;
    };
    const hasIdle = typeof w.requestIdleCallback === "function";
    const idle = hasIdle ? w.requestIdleCallback!(start, { timeout: 1500 }) : window.setTimeout(start, 600);

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      if (hasIdle) w.cancelIdleCallback?.(idle);
      else clearTimeout(idle);
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
