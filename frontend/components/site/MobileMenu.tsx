"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { AnrilLogo } from "@/components/logo";
import { useFocusTrap } from "./hooks";
import { DEMO_HREF, DEMO_LABEL, NAV, SIGN_IN_HREF } from "./content";
import s from "./MobileMenu.module.css";

type Props = { open: boolean; onClose: () => void };

/** Full-screen menu for narrow screens. Traps focus, closes on Escape or on any link. */
export function MobileMenu({ open, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useFocusTrap(panelRef, open);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div
      ref={panelRef}
      id="site-menu"
      className={s.panel}
      role="dialog"
      aria-modal="true"
      aria-label="Menu"
      hidden={!open}
    >
      <div className={s.top}>
        <AnrilLogo height={24} aria-hidden="true" focusable="false" />
        <button ref={closeRef} type="button" className={s.close} onClick={onClose}>
          Close
        </button>
      </div>
      <nav aria-label="Main" className={s.nav}>
        <ul className={s.list}>
          {NAV.map((item) => (
            <li key={item.href} className={s.group}>
              <Link prefetch={false} href={item.href} className={s.main} onClick={onClose}>
                {item.label}
              </Link>
              {item.groups ? (
                <>
                  {item.groups.map((g) => (
                    <div key={g.heading}>
                      <p className={s.subH}>{g.heading}</p>
                      <ul className={`${s.sub} ${s.one}`}>
                        {g.links.map((child) => (
                          <li key={child.href}>
                            <Link prefetch={false} href={child.href} className={s.subLink} onClick={onClose}>
                              {child.label}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {item.more && (
                    <p className={s.subMore}>
                      {item.more.line} ·{" "}
                      <Link prefetch={false} href={item.more.link.href} onClick={onClose}>
                        {item.more.link.label} →
                      </Link>
                    </p>
                  )}
                </>
              ) : item.children && (
                <ul className={s.sub}>
                  {item.children.map((child) => (
                    <li key={child.href}>
                      <Link prefetch={false} href={child.href} className={s.subLink} onClick={onClose}>
                        {child.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <div className={s.actions}>
        <a className={s.demo} href={DEMO_HREF} onClick={onClose}>
          {DEMO_LABEL}
        </a>
        <Link prefetch={false} className={s.signIn} href={SIGN_IN_HREF}>
          Sign in
        </Link>
      </div>
    </div>
  );
}
