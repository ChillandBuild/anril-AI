"use client";

import Link from "next/link";
import { useCallback, useId, useRef, useState } from "react";
import { useDismiss } from "./hooks";
import type { NavItem } from "./content";
import s from "./SiteHeader.module.css";

export function Chevron() {
  return (
    <svg viewBox="0 0 12 8" width="12" height="8" aria-hidden="true" focusable="false">
      <path d="M1 1.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A top-level link to its page, plus a chevron button that opens a short list of deeper links. */
export function NavDropdown({ item }: { item: NavItem }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLLIElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  const close = useCallback((viaEscape: boolean) => {
    setOpen(false);
    if (viaEscape) buttonRef.current?.focus();
  }, []);
  useDismiss(rootRef, open, close);

  return (
    <li
      ref={rootRef}
      className={s.item}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <Link prefetch={false} href={item.href} className={s.link}>
        {item.label}
      </Link>
      <button
        ref={buttonRef}
        type="button"
        className={s.chev}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`More ${item.label} links`}
        // A mouse has already opened the panel on hover, so its click must not toggle it shut.
        // Keyboard activation (detail === 0) toggles.
        onClick={(e) => setOpen((v) => (e.detail === 0 ? !v : true))}
      >
        <Chevron />
      </button>
      {item.groups ? (
        <div id={panelId} className={`${s.panel} ${s.wide}`} hidden={!open}>
          <div className={s.cols}>
            {item.groups.map((g) => (
              <div key={g.heading}>
                <p className={s.colH}>{g.heading}</p>
                <ul>
                  {g.links.map((child) => (
                    <li key={child.href}>
                      <Link prefetch={false} href={child.href} className={s.panelLink} onClick={() => setOpen(false)}>
                        {child.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {item.more && (
            <p className={s.panelFoot}>
              <span>{item.more.line}</span>
              <Link prefetch={false} href={item.more.link.href} onClick={() => setOpen(false)}>
                {item.more.link.label} →
              </Link>
            </p>
          )}
        </div>
      ) : (
        <ul id={panelId} className={s.panel} hidden={!open}>
          {item.children?.map((child) => (
            <li key={child.href}>
              <Link prefetch={false} href={child.href} className={s.panelLink} onClick={() => setOpen(false)}>
                {child.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
