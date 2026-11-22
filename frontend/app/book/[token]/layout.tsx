import type { Metadata } from "next";

// Customer-facing and private to whoever holds the link: keep it out of search results.
export const metadata: Metadata = {
  title: "Book a time",
  robots: { index: false, follow: false },
};

export default function BookLayout({ children }: { children: React.ReactNode }) {
  return children;
}
