import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { ChannelFlow } from "@/components/site/ChannelFlow";
import { DemoSection } from "@/components/site/DemoSection";
import { FeatureRow } from "@/components/site/FeatureRow";
import { FEATURES } from "@/components/site/features";
import { HomeHero } from "@/components/site/HomeHero";
import { ChannelStrip, IndustryList, ProductFacts } from "@/components/site/HomeBlocks";
import { HoursRuler } from "@/components/site/HoursRuler";
import { Reviews } from "@/components/site/Reviews";
import { Frame, Kicker } from "@/components/site/primitives";

export const metadata: Metadata = {
  title: { absolute: "Anril AI | Answer every enquiry. Call the right lead first." },
  description:
    "Anril AI replies to every WhatsApp, Instagram and Facebook enquiry in seconds, in Tamil, English or Tanglish. Scores leads and takes payments. From ₹999/month.",
};

export default function NewHomePage() {
  return (
    <>
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

        <div id="how">
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
        <Reviews />
        <IndustryList />
        <DemoSection />
      </Frame>
    </>
  );
}
