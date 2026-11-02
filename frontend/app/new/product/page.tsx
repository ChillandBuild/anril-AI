import type { Metadata } from "next";
import ui from "@/components/site/site.module.css";
import { ChannelFlow } from "@/components/site/ChannelFlow";
import { DemoSection } from "@/components/site/DemoSection";
import { FeatureRow } from "@/components/site/FeatureRow";
import { FEATURES } from "@/components/site/features";
import { ProductIntro } from "@/components/site/ProductIntro";
import { BeforeAfter } from "@/components/site/BeforeAfter";
import { Frame, Kicker } from "@/components/site/primitives";
import { JsonLd, breadcrumbSchema } from "@/components/site/schema";

export const metadata: Metadata = {
  title: { absolute: "Bulk WhatsApp, AI Chatbot & Telecalling CRM | Anril AI" },
  description:
    "Bulk WhatsApp sender, AI chatbot in Tanglish, lead management with Hot/Warm/Cold scoring, payment links and telecaller call tracking in one platform.",
  alternates: { canonical: "/product" },
};

export default function ProductPage() {
  return (
    <Frame>
      <JsonLd data={breadcrumbSchema([["Products", "/product"]])} />
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
