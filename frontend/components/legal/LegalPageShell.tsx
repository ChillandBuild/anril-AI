import type { ReactNode } from "react";
import { SiteChrome } from "@/components/site/SiteChrome";
import ui from "@/components/site/site.module.css";
import { REGISTERED_OFFICE } from "@/components/site/content";

interface LegalPageShellProps {
  title: string;
  subtitle: string;
  effectiveDate: string;
  children: ReactNode;
}

/** Legal and contact pages share the public site's header, menu and footer, so they feel like the rest of the site. */
export function LegalPageShell({ title, subtitle, effectiveDate, children }: LegalPageShellProps) {
  return (
    <SiteChrome>
      <div className={`${ui.legal} max-w-3xl mx-auto px-5 sm:px-6 pt-32 sm:pt-36 pb-16 sm:pb-20`}>
        <div className="text-xs font-semibold uppercase tracking-wide text-primary mb-2">{subtitle}</div>
        <h1 className="text-3xl md:text-4xl font-bold text-ink mb-2">{title}</h1>
        <div className="text-sm text-ink-muted mb-8 sm:mb-10">Effective Date: {effectiveDate}</div>
        <article className="text-base md:text-sm">{children}</article>
        <div className="mt-12 pt-6 border-t border-border text-sm text-ink-muted">Bloom Matrix — {REGISTERED_OFFICE}</div>
      </div>
    </SiteChrome>
  );
}

export function LegalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold text-ink mt-2 mb-3">{title}</h2>
      <div className="space-y-3 text-base md:text-sm leading-relaxed text-ink-secondary">{children}</div>
    </section>
  );
}

export function LegalList({ items }: { items: ReactNode[] }) {
  return (
    <ul className="list-disc pl-5 space-y-1.5">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}
