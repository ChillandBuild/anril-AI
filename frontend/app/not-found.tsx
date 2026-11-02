import type { Metadata } from "next";
import Link from "next/link";
import { AnrilLogo } from "@/components/logo";

export const metadata: Metadata = {
  title: "Page not found",
  robots: { index: false },
};

const LINKS = [
  { href: "/", label: "Home", note: "What Anril AI does" },
  { href: "/product", label: "Products", note: "Chatbot, bulk WhatsApp, CRM, telecalling and payments" },
  { href: "/pricing", label: "Pricing", note: "Plans from ₹999 a month" },
  { href: "/contact", label: "Contact", note: "Our Coimbatore office and WhatsApp" },
] as const;

export default function NotFound() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="max-w-3xl mx-auto px-6 py-6">
          <Link href="/" aria-label="Anril home">
            <AnrilLogo height={26} className="text-ink" />
          </Link>
        </div>
      </header>
      <main className="max-w-3xl mx-auto px-6 py-16">
        <p className="text-xs font-semibold uppercase tracking-wide text-primary mb-2">Error 404</p>
        <h1 className="text-3xl md:text-4xl font-bold text-ink mb-3">We can&apos;t find that page</h1>
        <p className="text-sm leading-relaxed text-ink-secondary mb-8">
          The link may be old or mistyped. These pages will get you back on track.
        </p>
        <ul className="grid gap-3 sm:grid-cols-2">
          {LINKS.map((l) => (
            <li key={l.href}>
              <Link href={l.href} className="card block hover:border-primary transition-colors">
                <span className="block text-sm font-semibold text-ink">{l.label}</span>
                <span className="block text-sm text-ink-secondary mt-1">{l.note}</span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
