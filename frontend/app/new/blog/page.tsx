import type { Metadata } from "next";
import { BlogIndex } from "@/components/site/BlogViews";

export const metadata: Metadata = {
  title: { absolute: "Blog: WhatsApp AI Agents, Lead Scoring & Telecalling | Anril AI" },
  description:
    "Plain answers on WhatsApp AI agents, bulk WhatsApp messaging, lead scoring and telecalling for Indian businesses, from the Anril AI team.",
  alternates: { canonical: "/blog" },
};

export default function BlogPage() {
  return <BlogIndex />;
}
