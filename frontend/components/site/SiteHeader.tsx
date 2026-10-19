"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnrilLogo } from "@/components/logo";
import { useScrolled } from "./hooks";
import { MobileMenu } from "./MobileMenu";
import { NavDropdown } from "./NavDropdown";
import { DEMO_HREF, DEMO_LABEL, NAV, SIGN_IN_HREF } from "./content";
import s from "./SiteHeader.module.css";

/** Clear over the home hero, easing into a frosted bar once the page scrolls (solid from the start on other pages). */
export function SiteHeader() {
  const pathname = usePathname();
  const scrolled = useScrolled(40);
  const [mounted, setMounted] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  // Without JavaScript the header stays in the page flow over the hero, so it never
  // floats white text over the white sections below. It only becomes fixed once mounted.
  useEffect(() => setMounted(true), []);
  useEffect(() => setMenuOpen(false), [pathname]);

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  }, []);

  // The home page is served at "/" (rewritten from /new), so both addresses count as home.
  const isHome = pathname === "/" || pathname === "/new";
  const solid = !isHome || scrolled;
  const cls = [s.hdr, mounted && s.live, solid && s.solid].filter(Boolean).join(" ");

  return (
    <header className={cls}>
      <div className={s.inner}>
        <Link prefetch={false} href="/" className={s.home} aria-label="Anril AI home">
          <AnrilLogo height={26} aria-hidden="true" focusable="false" />
        </Link>
        <div className={s.right}>
          <nav aria-label="Main" className={s.nav}>
            <ul className={s.links}>
              {NAV.map((item) =>
                item.children ? (
                  <NavDropdown key={item.href} item={item} />
                ) : (
                  <li key={item.href} className={s.item}>
                    <Link prefetch={false} href={item.href} className={s.link} aria-current={pathname === item.href ? "page" : undefined}>
                      {item.label}
                    </Link>
                  </li>
                ),
              )}
            </ul>
          </nav>
          <div className={s.actions}>
            <Link prefetch={false} className={s.login} href={SIGN_IN_HREF}>
              Sign in
            </Link>
            <a className={s.cta} href={DEMO_HREF}>
              {DEMO_LABEL}
            </a>
            <button
              ref={menuButtonRef}
              type="button"
              className={s.menuBtn}
              aria-expanded={menuOpen}
              aria-controls="site-menu"
              onClick={() => setMenuOpen(true)}
            >
              Menu
            </button>
          </div>
        </div>
      </div>
      <MobileMenu open={menuOpen} onClose={closeMenu} />
    </header>
  );
}
