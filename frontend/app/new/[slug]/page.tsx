import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LandingPage } from "@/components/site/LandingPage";
import { PRODUCT_PAGES, findLanding } from "@/components/site/landing-content";

// Only the product slugs exist; anything else is a 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return PRODUCT_PAGES.map((p) => ({ slug: p.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const { slug } = params;
  const page = findLanding(PRODUCT_PAGES, slug);
  if (!page) return {};
  return { title: { absolute: page.title }, description: page.description, alternates: { canonical: page.path } };
}

export default function ProductLandingPage({ params }: { params: { slug: string } }) {
  const { slug } = params;
  const page = findLanding(PRODUCT_PAGES, slug);
  if (!page) notFound();
  return <LandingPage page={page} parent={["Products", "/product"]} />;
}
