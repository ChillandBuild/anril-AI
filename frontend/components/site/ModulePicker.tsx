"use client";

import { useState } from "react";
import { CONTACT_EMAIL, MODULES } from "./content";
import m from "./Modules.module.css";
import s from "./ModulePicker.module.css";

/** Four module cards the visitor can tick. The ticked ones are summed into a quote request by email; no prices are shown. */
export function ModulePicker() {
  const [picked, setPicked] = useState<readonly string[]>([]);
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const chosen = MODULES.filter((mod) => picked.includes(mod.id));
  const names = chosen.map((mod) => mod.name);
  const subject = encodeURIComponent("Anril AI pricing");
  const body = encodeURIComponent(`I would like a quote for: ${names.join(", ")}.\n\nHow enquiries reach us today:\n`);

  return (
    <div className={s.wrap}>
      <ul className={s.grid} aria-label="Modules">
        {MODULES.map((mod, i) => {
          const on = picked.includes(mod.id);
          return (
            <li key={mod.id} id={mod.id} className={`${s.card} ${on ? s.on : ""}`} data-reveal style={{ "--rd": `${i * 70}ms` } as React.CSSProperties}>
              <div className={s.head}>
                <span className={m.num}>Module {i + 1}</span>
                <button type="button" className={s.toggle} aria-pressed={on} aria-label={`${on ? "Remove" : "Add"} ${mod.name} ${on ? "from" : "to"} my quote`} onClick={() => toggle(mod.id)}>
                  <span className={s.box} aria-hidden="true">
                    <svg viewBox="0 0 20 20" width="14" height="14" focusable="false">
                      <path d="M4 10.5l4 4 8-9" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                  {on ? "Added" : "Add to quote"}
                </button>
              </div>
              <h2 className={s.title}>{mod.name}</h2>
              <p>{mod.tagline}</p>
              <ul className={m.feats}>
                {mod.features.map(([name, text]) => (
                  <li key={name}>
                    <b>{name}</b>
                    {text}
                  </li>
                ))}
              </ul>
              <p className={m.flow}>{mod.flow}</p>
              <p className={m.price}>Contact us for pricing</p>
            </li>
          );
        })}
      </ul>

      <div className={s.summary} aria-live="polite">
        {chosen.length === 0 ? (
          <p className={s.hint}>Tick the modules you need and your combination appears here.</p>
        ) : (
          <>
            <div>
              <span className={m.num}>Your combination</span>
              <p className={s.combo}>{names.join(" + ")}</p>
              <p className={s.flows}>{chosen.map((c) => c.flow).join("  ·  ")}</p>
            </div>
            <a className={s.quote} href={`mailto:${CONTACT_EMAIL}?subject=${subject}&body=${body}`}>
              Request a quote for these
            </a>
          </>
        )}
      </div>
    </div>
  );
}
