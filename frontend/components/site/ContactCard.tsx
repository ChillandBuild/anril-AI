"use client";

import { useRef, useState } from "react";
import { CONTACT_EMAIL } from "./content";
import ui from "./site.module.css";
import s from "./AboutBlocks.module.css";

/** The contact email set large, with a button that copies it. If copying is refused, the address is selected so it can be copied by hand. */
export function ContactCard() {
  const [done, setDone] = useState(false);
  const mailRef = useRef<HTMLAnchorElement>(null);
  const timer = useRef<number>();

  async function copy() {
    try {
      await navigator.clipboard.writeText(CONTACT_EMAIL);
    } catch {
      const sel = window.getSelection();
      if (mailRef.current && sel) {
        sel.selectAllChildren(mailRef.current);
      }
      return;
    }
    setDone(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDone(false), 2000);
  }

  return (
    <div className={s.contact} data-reveal>
      <div className={s.contactRow}>
        <a ref={mailRef} className={s.email} href={`mailto:${CONTACT_EMAIL}`}>
          {CONTACT_EMAIL}
        </a>
        <button type="button" className={s.copy} onClick={copy} data-done={done || undefined}>
          {done ? "Copied" : "Copy email"}
        </button>
      </div>
      <span className={ui.sr} role="status">
        {done ? "Email address copied" : ""}
      </span>
    </div>
  );
}
