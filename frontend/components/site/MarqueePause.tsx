"use client";

import { useState } from "react";
import s from "./HomeBlocks.module.css";

/** Stops and restarts the channel marquee, for people on touch screens or keyboards who cannot hover to pause it. */
export function MarqueePause() {
  const [paused, setPaused] = useState(false);
  return (
    <button
      type="button"
      className={s.pause}
      aria-pressed={paused}
      onClick={(e) => {
        const next = !paused;
        setPaused(next);
        const strip = e.currentTarget.closest("section")?.querySelector("[data-marquee]");
        if (strip) strip.toggleAttribute("data-paused", next);
      }}
    >
      {paused ? "Play" : "Pause"}
    </button>
  );
}
