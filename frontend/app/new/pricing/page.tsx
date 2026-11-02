import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { CONTACT_EMAIL, DEMO_HREF, DEMO_LABEL } from "@/components/site/content";
import { DemoSection } from "@/components/site/DemoSection";
import { Faq } from "@/components/site/Faq";
import { ModuleChips } from "@/components/site/ModuleChips";
import { ModulePicker } from "@/components/site/ModulePicker";
import { PageIntro } from "@/components/site/PageIntro";
import { PRICING_FAQ } from "@/components/site/faqs";
import { Frame, Kicker } from "@/components/site/primitives";
import { JsonLd, SOFTWARE, breadcrumbSchema, faqSchema } from "@/components/site/schema";

export const metadata: Metadata = {
  title: { absolute: "WhatsApp API & Chatbot Pricing India – from ₹999 | Anril" },
  description:
    "Anril AI plans start from ₹999 a month (plus GST). WhatsApp message charges from Meta are separate. Cancel anytime, GST invoice. Free demo.",
  alternates: { canonical: "/pricing" },
};

const PRICING_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Anril AI pricing")}`;


export default function PricingPage() {
  return (
    <Frame>
      <JsonLd data={SOFTWARE} />
      <JsonLd data={faqSchema(PRICING_FAQ)} />
      <JsonLd data={breadcrumbSchema([["Pricing", "/pricing"]])} />
      <PageIntro
        title="Plans and pricing"
        lede="Plans start from ₹999 a month (plus GST). Choose the modules your business needs, and we'll suggest the right plan in a free demo."
      >
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <a className={ui.btn} href={PRICING_MAILTO}>
            Get your plan
          </a>
          <a className={ui.tlink} href={DEMO_HREF}>
            {DEMO_LABEL}
          </a>
        </div>
      </PageIntro>
      <ModuleChips />
      <ModulePicker />
      <section className={ui.band} aria-labelledby="faq-h">
        <Kicker>Pricing</Kicker>
        <h2 className={ui.secH} id="faq-h">Questions about pricing</h2>
        <Faq items={PRICING_FAQ.map((f) => ({ q: f.q, a: f.a }))} />
      </section>
      <DemoSection />
    </Frame>
  );
}
