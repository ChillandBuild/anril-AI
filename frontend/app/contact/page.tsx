import type { Metadata } from "next";
import Link from "next/link";
import ui from "@/components/site/site.module.css";
import { CONTACT_EMAIL, MAPS_URL, OFFICE_GEO, OFFICE_LINE, PHONE, REGISTERED_OFFICE } from "@/components/site/content";
import { DemoSection } from "@/components/site/DemoSection";
import { PageIntro } from "@/components/site/PageIntro";
import { Frame } from "@/components/site/primitives";
import { JsonLd, breadcrumbSchema } from "@/components/site/schema";
import { SiteChrome } from "@/components/site/SiteChrome";
import s from "./contact.module.css";

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
    <SiteChrome>
      <Frame>
        <JsonLd data={breadcrumbSchema([["Contact", "/contact"]])} />
        <PageIntro
          kicker="Contact"
          title="Talk to us"
          lede="For demos, support, sales or privacy requests. Reach us on WhatsApp, email or at our office."
        />
        <section className={ui.band} aria-label="Ways to reach us">
          <ul className={s.boxes}>
            <li>
              <h2 className={ui.kicker}>WhatsApp</h2>
              <p className={s.big}>{PHONE.display}</p>
              <a className={ui.btn} href={PHONE.whatsapp} rel="noopener">
                Chat now
              </a>
            </li>
            <li>
              <h2 className={ui.kicker}>Email</h2>
              <p className={s.big}>
                <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
              </p>
            </li>
            <li>
              <h2 className={ui.kicker}>Hours</h2>
              <p className={s.big}>Mon–Sat, 10–6</p>
              <p>Closed on government holidays</p>
            </li>
            <li>
              <h2 className={ui.kicker}>Office (demos held here)</h2>
              <address>{OFFICE_LINE}</address>
            </li>
          </ul>
          <iframe
            title="Map showing the Anril AI office in Coimbatore"
            src={MAP_SRC}
            className={s.map}
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
          <a className={ui.tlink} href={MAPS_URL} rel="noopener">
            Open in Google Maps
          </a>
          <p className={s.note}>
            Data deletion or privacy requests can also be sent in writing to Bloom Matrix&rsquo;s registered office,{" "}
            {REGISTERED_OFFICE}, marked &ldquo;Data Deletion Request&rdquo;. See our{" "}
            <Link prefetch={false} href="/privacy-policy">privacy policy</Link> and{" "}
            <Link prefetch={false} href="/terms-and-conditions">terms and conditions</Link>.
          </p>
        </section>
        <DemoSection />
      </Frame>
    </SiteChrome>
  );
}
