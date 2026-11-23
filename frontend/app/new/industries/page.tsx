import type { Metadata } from "next";
import { DemoSection } from "@/components/site/DemoSection";
import { IndustryGrid, MoreIndustries } from "@/components/site/IndustryGrid";
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
      <IndustryIntro lede="Wherever people ask before they buy, Anril AI answers the enquiry, marks the lead hot, warm or cold, and sends the hot ones to your team. Here is how that could look in the industries we work with most.">
        <Eg>The conversations below are examples, not customer data.</Eg>
      </IndustryIntro>
      <IndustryGrid />
      <MoreIndustries />
      <DemoSection />
    </Frame>
  );
}
