import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { ChannelFlow } from "@/components/site/ChannelFlow";
import { DemoSection } from "@/components/site/DemoSection";
import { FeatureRow } from "@/components/site/FeatureRow";
import { FEATURES } from "@/components/site/features";
import { ProductIntro } from "@/components/site/ProductIntro";
import { BeforeAfter } from "@/components/site/BeforeAfter";
import { Frame, Kicker } from "@/components/site/primitives";

export const metadata: Metadata = {
  title: "Products",
  description:
    "AI replies on WhatsApp, web chat and phone, lead scoring, telecaller routing and call scoring, in one place.",
};

export default function ProductPage() {
  return (
    <Frame>
      <ProductIntro />
      {FEATURES.map((f, i) => (
        <FeatureRow key={f.id} feature={f} flip={i % 2 === 1} showPoints linkHref="#demo" linkLabel="See it in a demo" />
      ))}
      <BeforeAfter />
      <section className={ui.band} id="channels" aria-labelledby="ch-h">
        <Kicker>Channels</Kicker>
        <h2 className={ui.secH} id="ch-h">Every channel, one list of leads</h2>
        <p className={ui.lede}>
          Enquiries from WhatsApp, Instagram, Facebook Messenger, Telegram, web chat and phone arrive in the same place and
          leave sorted, with the hot ones at the top.
        </p>
        <ChannelFlow />
      </section>
      <DemoSection />
    </Frame>
  );
}
