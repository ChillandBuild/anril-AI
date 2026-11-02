import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { HOURS, OFFICE_LINE, PHONE } from "@/components/site/content";
import { ContactCard } from "@/components/site/ContactCard";
import { DemoSection } from "@/components/site/DemoSection";
import { MakerPanel, Principles } from "@/components/site/AboutBlocks";
import { PageIntro } from "@/components/site/PageIntro";
import { Frame, Kicker } from "@/components/site/primitives";
import { JsonLd, breadcrumbSchema } from "@/components/site/schema";

export const metadata: Metadata = {
  title: { absolute: "About Anril AI – AI Sales Platform from Coimbatore" },
  description:
    "Anril AI is built by Bloom Matrix in Coimbatore, Tamil Nadu. One platform to reach customers, reply with AI, take payments and track calls.",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <Frame>
      <JsonLd data={breadcrumbSchema([["About", "/about"]])} />
      <PageIntro
        title="About Anril AI"
        lede="From first message to final sale. Anril AI answers enquiries, shows you which leads are ready to buy, and helps your team call the right lead first."
      />
      <Principles />
      <MakerPanel />
      <section className={ui.band} id="contact" aria-labelledby="contact-h">
        <Kicker>Contact</Kicker>
        <h2 className={ui.secH} id="contact-h">Talk to us</h2>
        <p className={ui.lede}>
          Visit our Coimbatore office, message us on WhatsApp, email us, or book a demo below.
        </p>
        <address className={ui.lede} style={{ fontStyle: "normal" }}>
          {OFFICE_LINE}, India
          <br />
          WhatsApp: <a href={PHONE.whatsapp} rel="noopener">{PHONE.display}</a>
          <br />
          {HOURS} (closed on government holidays)
        </address>
        <ContactCard />
      </section>
      <DemoSection />
    </Frame>
  );
}
