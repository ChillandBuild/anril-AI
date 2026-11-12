import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { DEMO_HREF, DEMO_LABEL } from "@/components/site/content";
import { DemoSection } from "@/components/site/DemoSection";
import { IndustryGrid } from "@/components/site/IndustryGrid";
import { IndustryIntro } from "@/components/site/IndustryIntro";
import { Eg, Frame } from "@/components/site/primitives";
import { JsonLd, breadcrumbSchema } from "@/components/site/schema";

export const metadata: Metadata = {
  title: { absolute: "Real Estate, School & Clinic Lead Management | Anril AI" },
  description:
    "Lead management and WhatsApp AI agent for real estate, education, healthcare, D2C brands and any business whose customers ask before they buy.",
  alternates: { canonical: "/industries" },
};

// What people ask is a plain description of each trade; the conversation and what
// happens next are illustrations, marked as examples on the page.
export default function IndustriesPage() {
  return (
    <Frame>
      <JsonLd data={breadcrumbSchema([["Industries", "/industries"]])} />
      <IndustryIntro lede="Wherever people ask before they buy, Anril AI answers the enquiry, marks the lead hot, warm or cold, and sends the hot ones to your team. Here is how that could look in a few industries.">
        <Eg>The conversations below are examples, not customer data.</Eg>
      </IndustryIntro>
      <IndustryGrid />
      <section className={ui.band} id="more" aria-labelledby="more-h">
        <h2 className={ui.secH} id="more-h">Your business</h2>
        <p className={ui.lede}>
          Retail, travel, events, home services, hospitality: if your customers ask before they buy, Anril AI answers
          them, marks each lead hot, warm or cold, and sends the hot ones to your team.
        </p>
        <p className={ui.lede}>Tell us how enquiries reach you today, and we will show you how Anril AI would handle them.</p>
        <a className={ui.tlink} href={DEMO_HREF}>
          {DEMO_LABEL}
        </a>
      </section>
      <DemoSection />
    </Frame>
  );
}
