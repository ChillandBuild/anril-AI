import type { Metadata } from "next";
import Link from "next/link";
import ui from "@/components/site/site.module.css";
import { ChannelFlow } from "@/components/site/ChannelFlow";
import { DemoSection } from "@/components/site/DemoSection";
import { FeatureRow } from "@/components/site/FeatureRow";
import { FEATURES } from "@/components/site/features";
import { HomeHero } from "@/components/site/HomeHero";
import { BuiltOnEnquiries, ChannelStrip, HomeModules, IndustryList, ProductFacts } from "@/components/site/HomeBlocks";
import { HoursRuler } from "@/components/site/HoursRuler";
import { Faq } from "@/components/site/Faq";
import { HOME_FAQ } from "@/components/site/faqs";
import { Frame, Kicker } from "@/components/site/primitives";
import { JsonLd, SOFTWARE, faqSchema } from "@/components/site/schema";

export const metadata: Metadata = {
  title: { absolute: "WhatsApp AI Chatbot & CRM for Business | Anril AI" },
  description:
    "Anril AI is a WhatsApp chatbot and CRM: replies to every WhatsApp, Instagram and Facebook enquiry in seconds, scores leads, takes payments. From ₹999/month.",
  alternates: { canonical: "/" },
};

export default function NewHomePage() {
  return (
    <>
      <JsonLd data={SOFTWARE} />
      <JsonLd data={faqSchema(HOME_FAQ)} />
      <HomeHero />
      <Frame>
        <ChannelStrip />

        <section className={ui.band} id="hours" aria-labelledby="hr-h" data-reveal="fade">
          <Kicker>After hours</Kicker>
          <h2 className={ui.secH} id="hr-h">Enquiries do not keep office hours</h2>
          <p className={ui.lede}>
            People message when it suits them. Anril AI answers each enquiry when it arrives, so the ones that come in
            at night are not waiting for you in the morning.
          </p>
          <HoursRuler />
        </section>

        <p className={ui.swipeHint} aria-hidden="true">Swipe sideways to see all four steps →</p>
        <div id="how" className={ui.swipe} role="region" aria-label="How Anril AI works, four steps" tabIndex={0}>
          {FEATURES.map((f, i) => (
            <FeatureRow key={f.id} feature={f} flip={i % 2 === 1} linkHref="#demo" linkLabel="See it in a demo" />
          ))}
        </div>

        <section className={ui.band} id="channels" aria-labelledby="ch-h" data-reveal>
          <Kicker>Channels</Kicker>
          <h2 className={ui.secH} id="ch-h">Every channel, one list of leads</h2>
          <p className={ui.lede}>
            Enquiries from WhatsApp, Instagram, Facebook Messenger, Telegram, web chat and phone arrive in the same
            place and leave sorted, with the hot ones at the top.
          </p>
          <ChannelFlow />
        </section>

        <ProductFacts />
        <BuiltOnEnquiries />
        <HomeModules />
        <IndustryList />
        <section className={ui.band} id="faq" aria-labelledby="faq-h">
          <Kicker>FAQ</Kicker>
          <h2 className={ui.secH} id="faq-h">Questions people ask</h2>
          <Faq
            items={HOME_FAQ.map((f) => ({
              q: f.q,
              a:
                f.q === "Do you build websites?" ? (
                  <>
                    {f.a} <Link prefetch={false} href="/website-development">See our website development page.</Link>
                  </>
                ) : (
                  f.a
                ),
            }))}
          />
        </section>
        <DemoSection />
      </Frame>
    </>
  );
}
