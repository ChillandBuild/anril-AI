"use client";

import { useId, useState, type ReactNode } from "react";
import s from "./Faq.module.css";

export type FaqItem = { q: string; a: ReactNode };

/** Questions that open one at a time with a smooth height change. The first starts open. */
export function Faq({ items }: { items: readonly FaqItem[] }) {
  const [open, setOpen] = useState<number | null>(0);
  const base = useId();
  return (
    <div className={s.faq}>
      {items.map(({ q, a }, i) => {
        const on = open === i;
        const id = `${base}-${i}`;
        return (
          <div key={q} className={s.item} data-open={on || undefined} data-reveal style={{ "--rd": `${i * 60}ms` } as React.CSSProperties}>
            <h3>
              <button type="button" id={`${id}-q`} aria-expanded={on} aria-controls={`${id}-a`} onClick={() => setOpen(on ? null : i)}>
                <span>{q}</span>
                <i aria-hidden="true" />
              </button>
            </h3>
            <div className={s.panel} id={`${id}-a`} role="region" aria-labelledby={`${id}-q`}>
              <div>
                <div className={s.answer}>{a}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
