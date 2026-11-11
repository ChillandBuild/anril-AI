import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import s from "@/components/site/Landing.module.css";
import { PHONE, SITE_URL } from "@/components/site/content";
import { DemoSection } from "@/components/site/DemoSection";
import { Faq } from "@/components/site/Faq";
import { PageIntro } from "@/components/site/PageIntro";
import { Frame, Kicker } from "@/components/site/primitives";
import { WEBSITE_FAQ } from "@/components/site/faqs";
import { JsonLd, ORG_ID, breadcrumbSchema, faqSchema } from "@/components/site/schema";

export const metadata: Metadata = {
  title: { absolute: "Website Development in Coimbatore | AI-Powered Websites | Anril AI" },
  description:
    "We build static, dynamic and AI-powered websites for businesses, with an AI chat that answers visitors and brings enquiries into one dashboard. Get a free AI website audit on WhatsApp.",
  alternates: { canonical: "/website-development" },
};

const AUDIT_HREF = `${PHONE.whatsapp}?text=Hi%2C%20free%20AI%20audit`;

const SERVICE = {
  "@context": "https://schema.org",
  "@type": "Service",
  name: "Website development",
  serviceType: "Website design and development",
  provider: { "@id": ORG_ID },
  areaServed: "India",
  url: `${SITE_URL}/website-development`,
  description: "Static, dynamic and AI-powered websites for businesses, with an AI chat that answers visitors.",
};

const TYPES: readonly (readonly [string, string])[] = [
  ["Static websites", "simple, fast information sites for your business."],
  ["Dynamic websites", "products, bookings, a blog or content you can update yourself."],
  ["AI-powered websites", "an AI chat on your site that answers visitors day and night, in English, Tamil or Tanglish."],
];

const INCLUDES: readonly string[] = [
  "Custom design in your brand colours and logo (not a copy-paste template)",
  "Mobile-friendly on phone, tablet and laptop",
  "WhatsApp chat button and one-tap call button",
  "Enquiry forms",
  "Website text written for you",
  "Basic Google setup: page titles, descriptions, sitemap and Google Search Console",
  "Link to your Google Business Profile",
  "Connection to Anril, so website enquiries land in the same dashboard as WhatsApp, Instagram and Facebook",
];

const STEPS: readonly string[] = [
  "Message us on WhatsApp and tell us about your business.",
  "We understand what you need and send a clear quote.",
  "We design, you review, we build and launch.",
];

export default function WebsiteDevelopmentPage() {
  return (
    <Frame>
      <JsonLd data={SERVICE} />
      <JsonLd data={faqSchema(WEBSITE_FAQ)} />
      <JsonLd data={breadcrumbSchema([["Website development", "/website-development"]])} />
      <PageIntro
        title="Websites that answer your customers"
        lede={`Most business websites only show information. When a customer asks "Price?" or "Is this available?", nobody replies and they leave. We build websites that look good, load fast, get found on Google and AI search, and can answer visitors instantly with an AI chat.`}
      >
        <div className={s.cta}>
          <a className={ui.btn} href={AUDIT_HREF} rel="noopener">
            Get free AI audit
          </a>
        </div>
      </PageIntro>

      <section className={ui.band} aria-labelledby="types-h" data-reveal>
        <Kicker>Website development</Kicker>
        <h2 className={ui.secH} id="types-h">Websites we build</h2>
        <div className={s.prose}>
          <ul>
            {TYPES.map(([name, text]) => (
              <li key={name}><b>{name}:</b> {text}</li>
            ))}
          </ul>
          <p>Every website is built for your business and can be customised as much as you need.</p>
        </div>
      </section>

      <section className={ui.band} aria-labelledby="inc-h" data-reveal>
        <h2 className={ui.secH} id="inc-h">What a website from us can include</h2>
        <div className={s.prose}>
          <ul>
            {INCLUDES.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          <p>Exact items depend on the package you choose. Our team explains them first.</p>
        </div>
      </section>

      <section className={ui.band} aria-labelledby="how-h" data-reveal>
        <h2 className={ui.secH} id="how-h">How it works</h2>
        <div className={s.prose}>
          <ol>
            {STEPS.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ol>
        </div>
      </section>

      <section className={ui.band} aria-labelledby="audit-h" data-reveal>
        <h2 className={ui.secH} id="audit-h">Free AI website audit</h2>
        <div className={s.prose}>
          <p>
            Already have a website? We&apos;ll check it for free and tell you what an AI website could improve: instant replies to
            visitors, being found on Google and AI search, and getting more enquiries. No website yet? You can ask too. Only 10
            businesses a month.
          </p>
        </div>
        <div className={s.cta}>
          <a className={ui.btn} href={AUDIT_HREF} rel="noopener">
            Get free AI audit
          </a>
        </div>
      </section>

      <section className={ui.band} id="faq" aria-labelledby="faq-h">
        <Kicker>FAQ</Kicker>
        <h2 className={ui.secH} id="faq-h">Questions people ask</h2>
        <Faq items={WEBSITE_FAQ.map((f) => ({ q: f.q, a: f.a }))} />
        <div className={s.cta}>
          <a className={ui.btn} href={PHONE.whatsapp} rel="noopener">
            Talk to us on WhatsApp
          </a>
        </div>
      </section>
      <DemoSection />
    </Frame>
  );
}
