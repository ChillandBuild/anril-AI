import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { CONTACT_EMAIL, DEMO_HREF, DEMO_LABEL } from "@/components/site/content";
import { DemoSection } from "@/components/site/DemoSection";
import { Faq } from "@/components/site/Faq";
import { ModuleChips } from "@/components/site/ModuleChips";
import { ModulePicker } from "@/components/site/ModulePicker";
import { PageIntro } from "@/components/site/PageIntro";
import { Frame, Kicker } from "@/components/site/primitives";

export const metadata: Metadata = {
  title: "Plans",
  description:
    "Anril AI is four modules in one connected platform: Reach, Engage, CallIQ and Commerce. Contact us for pricing.",
};

const PRICING_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Anril AI pricing")}`;

// Answers that hold whatever the quote says; billing terms are given in the quote itself.
const FAQ = [
  {
    q: "How much does Anril AI cost?",
    a: (
      <>
        Pricing depends on the modules you use and the size of your team. Email{" "}
        <a href={PRICING_MAILTO}>{CONTACT_EMAIL}</a> or book a demo, and we will send you a quote.
      </>
    ),
  },
  {
    q: "What will my quote include?",
    a: "The modules we suggest for your business, the price, how billing works, taxes, and how WhatsApp message charges from Meta are handled.",
  },
  {
    q: "Can I see it working before I decide?",
    a: "Yes. Book a demo and we will show you Anril AI answering enquiries like the ones your business gets.",
  },
  {
    q: "Which channels does it work on?",
    a: "WhatsApp, Instagram, Facebook Messenger, Telegram and web chat, with phone calls through CallIQ.",
  },
  {
    q: "How do I get started?",
    a: "Tell us how enquiries reach you today and who follows them up. We will suggest the modules that fit and take you through setup.",
  },
];

export default function PricingPage() {
  return (
    <Frame>
      <PageIntro
        title="Plans"
        lede="Four modules, one connected platform. Choose the ones your business needs, and contact us for pricing."
      >
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <a className={ui.btn} href={PRICING_MAILTO}>
            Contact us for pricing
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
        <Faq items={FAQ} />
      </section>
      <DemoSection />
    </Frame>
  );
}
