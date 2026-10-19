import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { CONTACT_EMAIL, MAKER } from "@/components/site/content";
import { ContactCard } from "@/components/site/ContactCard";
import { DemoSection } from "@/components/site/DemoSection";
import { MakerPanel, Principles } from "@/components/site/AboutBlocks";
import { PageIntro } from "@/components/site/PageIntro";
import { Frame, Kicker } from "@/components/site/primitives";

export const metadata: Metadata = {
  title: "Company",
  description: `Anril AI is a product of ${MAKER.name}. Talk to us: ${CONTACT_EMAIL}.`,
};

export default function AboutPage() {
  return (
    <Frame>
      <PageIntro
        title="About Anril AI"
        lede="From first message to final sale. Anril AI answers enquiries, shows you which leads are ready to buy, and helps your team call the right lead first."
      />
      <Principles />
      <MakerPanel />
      <section className={ui.band} id="contact" aria-labelledby="contact-h">
        <Kicker>Contact</Kicker>
        <h2 className={ui.secH} id="contact-h">Talk to us</h2>
        <p className={ui.lede}>Email us, or book a demo below.</p>
        <ContactCard />
      </section>
      <DemoSection />
    </Frame>
  );
}
