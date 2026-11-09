import type { Metadata } from "next";
import Link from "next/link";
import { Clock, Mail, MapPin, MessageCircle } from "lucide-react";
import { LegalPageShell } from "@/components/legal/LegalPageShell";
import { CONTACT_EMAIL, HOURS, MAPS_URL, OFFICE_GEO, OFFICE_LINE, PHONE, REGISTERED_OFFICE } from "@/components/site/content";
import { JsonLd, breadcrumbSchema } from "@/components/site/schema";

// The embed uses the exact pin, not a typed address, so it always lands on the office.
const MAP_SRC = `https://www.google.com/maps?q=${OFFICE_GEO.latitude},${OFFICE_GEO.longitude}&z=17&output=embed`;

export const metadata: Metadata = {
  title: { absolute: "Contact Anril AI – Coimbatore | WhatsApp 90473 70380" },
  description:
    "Book a free demo online or at our Coimbatore office. Mon–Sat, 10 AM–6 PM. WhatsApp +91 90473 70380.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  return (
    <LegalPageShell title="Contact Us" subtitle="Anril — a Bloom Matrix product" effectiveDate="14 June 2026">
      <JsonLd data={breadcrumbSchema([["Contact", "/contact"]])} />
      <p className="text-base md:text-sm leading-relaxed text-ink-secondary mb-10">
        For demos, support, sales, privacy requests, or any other questions about Anril, reach us below.
      </p>

      <div className="mb-6">
        <div className="card">
          <div className="w-10 h-10 rounded-lg bg-primary-light flex items-center justify-center mb-4">
            <MapPin size={18} className="text-primary" />
          </div>
          <p className="text-base md:text-sm font-semibold text-ink mb-1">Office (demos held here)</p>
          <address className="text-base md:text-sm text-ink-secondary leading-relaxed not-italic">{OFFICE_LINE}, India</address>
          <ul className="mt-4 space-y-1 text-base md:text-sm text-ink-secondary">
            <li className="flex items-center gap-2 min-h-[44px]">
              <MessageCircle size={14} className="text-primary" aria-hidden="true" />
              WhatsApp:{" "}
              <a href={PHONE.whatsapp} rel="noopener" className="text-primary hover:underline">
                {PHONE.display}
              </a>
            </li>
            <li className="flex items-center gap-2 min-h-[44px]">
              <Mail size={14} className="text-primary" aria-hidden="true" />
              <a href={`mailto:${CONTACT_EMAIL}`} className="text-primary hover:underline">
                {CONTACT_EMAIL}
              </a>
            </li>
            <li className="flex items-center gap-2 min-h-[44px]">
              <Clock size={14} className="text-primary" aria-hidden="true" />
              {HOURS} (closed on government holidays)
            </li>
          </ul>
          <iframe
            title="Map showing the Anril AI office in Coimbatore"
            src={MAP_SRC}
            className="mt-5 w-full h-64 rounded-lg border-0"
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
          <p className="mt-2 text-base md:text-sm">
            <a href={MAPS_URL} rel="noopener" className="text-primary hover:underline inline-flex items-center min-h-[44px]">
              Open in Google Maps
            </a>
          </p>
        </div>
      </div>

      <div className="mb-10">
        <div className="card">
          <p className="text-base md:text-sm font-semibold text-ink mb-1">Registered office (Bloom Matrix)</p>
          <address className="text-base md:text-sm text-ink-secondary leading-relaxed not-italic">{REGISTERED_OFFICE}</address>
        </div>
      </div>

      <p className="text-base md:text-sm leading-relaxed text-ink-secondary">
        Data deletion or privacy requests can be sent in writing to our registered office address above, marked
        &ldquo;Data Deletion Request&rdquo;. See our{" "}
        <Link href="/privacy-policy" className="text-primary hover:underline">
          Privacy Policy
        </Link>{" "}
        and{" "}
        <Link href="/terms-and-conditions" className="text-primary hover:underline">
          Terms &amp; Conditions
        </Link>{" "}
        for further details.
      </p>
    </LegalPageShell>
  );
}
