import Link from "next/link";
import { AnrilLogo } from "@/components/logo";
import { CONTACT_EMAIL, DEMO_HREF, DEMO_LABEL, HOURS, LEGAL_LINKS, MAKER, NAV, OFFICE_LINE, PHONE, SOCIAL } from "./content";
import s from "./SiteFooter.module.css";

const PRODUCT = NAV.find((n) => n.label === "Products")?.children ?? [];
const COMPANY = [
  { label: "About", href: "/about" },
  { label: "Plans", href: "/pricing" },
  { label: "Industries", href: "/industries" },
  { label: "Contact", href: "/contact" },
];
const LEGAL = LEGAL_LINKS.filter((l) => l.label !== "Contact");

/** A navy close to every page: the promise again, three link columns, and the wordmark set large. */
export function SiteFooter() {
  return (
    <footer className={s.footer}>
      <div className={s.inner}>
        <div className={s.top}>
          <div className={s.lead}>
            <p>Answer every enquiry. Call the right lead first.</p>
            <a className={s.cta} href={DEMO_HREF}>{DEMO_LABEL}</a>
            <p className={s.also}>
              We also build <Link prefetch={false} href="/website-development">AI-powered websites</Link>.
            </p>
          </div>
          <nav aria-label="Footer" className={s.cols}>
            <div>
              <h2>Product</h2>
              <ul>
                {PRODUCT.map((l) => (
                  <li key={l.href}><Link prefetch={false} href={l.href}>{l.label}</Link></li>
                ))}
              </ul>
            </div>
            <div>
              <h2>Company</h2>
              <ul>
                {COMPANY.map((l) => (
                  <li key={l.href}><Link prefetch={false} href={l.href}>{l.label}</Link></li>
                ))}
              </ul>
            </div>
            <div>
              <h2>Legal</h2>
              <ul>
                {LEGAL.map((l) => (
                  <li key={l.href}><Link prefetch={false} href={l.href}>{l.label}</Link></li>
                ))}
              </ul>
            </div>
          </nav>
        </div>
        <Link prefetch={false} href="/" className={s.mark} aria-label="Anril AI home">
          <AnrilLogo aria-hidden="true" focusable="false" />
        </Link>
        <div className={s.base}>
          <p>
            A product of{" "}
            <a href={MAKER.href} rel="noopener">
              {MAKER.name}
            </a>
          </p>
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </div>
        <div className={`${s.base} ${s.details}`}>
          <address>{OFFICE_LINE}, India</address>
          <p>
            WhatsApp:{" "}
            <a href={PHONE.whatsapp} rel="noopener">
              {PHONE.display}
            </a>
          </p>
          <p>{HOURS}</p>
          <ul className={s.social}>
            {SOCIAL.map((l) => (
              <li key={l.href}>
                <a href={l.href} rel="noopener">
                  {l.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
        <p className={s.legalnote}>
          WhatsApp, Instagram, Facebook and Meta are trademarks of Meta Platforms, Inc. Razorpay is a trademark of Razorpay.
          Anril AI is an independent product and is not affiliated with or endorsed by them.
        </p>
      </div>
    </footer>
  );
}
