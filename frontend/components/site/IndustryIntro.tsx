"use client";

import { useEffect, useState, type ReactNode } from "react";
import ui from "./site.module.css";
import { prefersReducedMotion } from "./motion-lib";
import s from "./IndustryIntro.module.css";

// The first word is the plain sentence, so it is what shows without motion or JavaScript.
const WORDS = ["any business", "a coaching institute", "a property developer", "a clinic", "a car showroom", "a factory", "a lender"] as const;
const FULL_TITLE = `Built for ${WORDS[0]} that runs on enquiries`;

/** Opening band of the Industries page. The title's industry changes every few seconds; screen readers get the full sentence once. */
export function IndustryIntro({ lede, children }: { lede: ReactNode; children?: ReactNode }) {
  const [i, setI] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion()) return;
    // One pass through the list, then it settles back on the plain sentence and stops.
    const id = window.setInterval(() => {
      setI((n) => {
        if (n + 1 >= WORDS.length) window.clearInterval(id);
        return (n + 1) % WORDS.length;
      });
    }, 2600);
    return () => window.clearInterval(id);
  }, []);

  return (
    <section className={`${ui.band} ${s.intro}`} aria-labelledby="page-h">
      <h1 id="page-h" className={s.title}>
        <span className={ui.sr}>{FULL_TITLE}</span>
        <span aria-hidden="true">
          Built for{" "}
          <span key={i} className={i === 0 ? s.word : `${s.word} ${s.swap}`}>
            {WORDS[i]}
          </span>{" "}
          that runs on enquiries
        </span>
      </h1>
      <p className={ui.lede}>{lede}</p>
      {children}
    </section>
  );
}
