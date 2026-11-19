import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { IndustryPage } from "@/components/site/IndustryPage";
import { INDUSTRY_PAGES, findIndustryPage } from "@/components/site/industry-pages";

// Only the industry slugs exist; anything else is a 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return INDUSTRY_PAGES.map((p) => ({ slug: p.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const page = findIndustryPage(params.slug);
  if (!page) return {};
  return {
    title: { absolute: page.title },
    description: page.description,
    // Hidden from visitors: people search "WhatsApp chatbot" far more than "WhatsApp AI agent".
    keywords: [...page.keywords],
    alternates: { canonical: page.path },
    openGraph: {
      siteName: "Anril AI",
      type: "website",
      locale: "en_IN",
      url: `https://www.anrilaitech.com${page.path}`,
      title: page.title,
      description: page.description,
      images: [{ url: "/og-image-v2.png", width: 1200, height: 630, alt: page.heroAlt }],
    },
    twitter: { card: "summary_large_image", title: page.title, description: page.description, images: ["/og-image-v2.png"] },
  };
}

export default function IndustryLandingPage({ params }: { params: { slug: string } }) {
  const page = findIndustryPage(params.slug);
  if (!page) notFound();
  return <IndustryPage page={page} />;
}
