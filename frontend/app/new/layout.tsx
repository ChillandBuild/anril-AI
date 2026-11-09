import type { Metadata } from "next";
import { SiteChrome } from "@/components/site/SiteChrome";

export const metadata: Metadata = {
  title: { default: "Anril AI", template: "%s | Anril AI" },
  // Live: this site is the homepage, so it is indexed like any public page.
};

export default function NewSiteLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <SiteChrome>{children}</SiteChrome>;
}
