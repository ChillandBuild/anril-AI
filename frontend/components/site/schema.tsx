import { CONTACT_EMAIL, MAKER, MAPS_URL, OFFICE, OFFICE_GEO, SITE_URL, SOCIAL, STARTING_PRICE } from "./content";

/** Hidden structured data for Google and AI tools. `data` is built here from the same constants the page shows. */
export function JsonLd({ data }: { data: object }) {
  // "<" is escaped so no string in the data can close the script tag early.
  const json = JSON.stringify(data).replace(/</g, "\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />;
}

export const ORG_ID = `${SITE_URL}/#org`;

export const ORGANIZATION = {
  "@context": "https://schema.org",
  "@type": ["Organization", "ProfessionalService"],
  "@id": ORG_ID,
  name: "Anril AI",
  alternateName: "Anril",
  url: `${SITE_URL}/`,
  logo: `${SITE_URL}/icons/anril-icon-192.png`,
  image: `${SITE_URL}/og-image.png`,
  priceRange: `From ${STARTING_PRICE} per month`,
  description:
    "AI-powered business growth and commerce platform: WhatsApp campaigns, AI replies, lead scoring, payments and call intelligence.",
  parentOrganization: { "@type": "Organization", name: MAKER.name, url: MAKER.href },
  telephone: "+91-9047370380",
  email: CONTACT_EMAIL,
  address: {
    "@type": "PostalAddress",
    streetAddress: OFFICE.street,
    addressLocality: OFFICE.city,
    addressRegion: OFFICE.region,
    postalCode: OFFICE.postalCode,
    addressCountry: "IN",
  },
  geo: { "@type": "GeoCoordinates", latitude: OFFICE_GEO.latitude, longitude: OFFICE_GEO.longitude },
  hasMap: MAPS_URL,
  openingHoursSpecification: [
    {
      "@type": "OpeningHoursSpecification",
      dayOfWeek: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
      opens: "10:00",
      closes: "18:00",
    },
  ],
  areaServed: ["IN", "Worldwide"],
  sameAs: SOCIAL.map((l) => l.href),
};

export const SOFTWARE = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Anril AI",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web browser",
  publisher: { "@id": ORG_ID },
  description:
    "WhatsApp campaigns (Reach), AI replies and lead scoring (Engage), payments, orders and inventory (Commerce), and Tamil call intelligence (CallIQ) in one connected platform.",
  // No aggregateRating until there are real public reviews.
  offers: {
    "@type": "Offer",
    price: STARTING_PRICE.replace(/[^\d]/g, ""),
    priceCurrency: "INR",
    description: "Starting price per month, plus GST",
    url: `${SITE_URL}/pricing`,
  },
};

export type FaqEntry = { q: string; a: string };

export function faqSchema(items: readonly FaqEntry[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((i) => ({
      "@type": "Question",
      name: i.q,
      acceptedAnswer: { "@type": "Answer", text: i.a },
    })),
  };
}

/** Home is added first; `trail` is the rest, e.g. [["Pricing", "/pricing"]] or [["Industries", "/industries"], ["Real estate", "/industries/real-estate"]]. */
export function breadcrumbSchema(trail: readonly (readonly [name: string, path: string])[]) {
  const all = [["Home", "/"] as const, ...trail];
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: all.map(([name, path], i) => ({
      "@type": "ListItem",
      position: i + 1,
      name,
      item: `${SITE_URL}${path}`,
    })),
  };
}

