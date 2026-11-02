import type { Metadata } from "next";
import localFont from "next/font/local";
import { SiteFooter } from "@/components/site/SiteFooter";
import { SiteHeader } from "@/components/site/SiteHeader";
import ui from "@/components/site/site.module.css";
import { Motion } from "@/components/site/Motion";
import { JsonLd, ORGANIZATION } from "@/components/site/schema";
import "@/components/site/motion.css";

// Serif for the marketing site's headings only, so the app's other pages never load it.
// Two static weights (about 23 KB each) instead of the 132 KB variable file with the
// optical-size axis; the mockup only uses 300 and 400.
const newsreader = localFont({
  src: [
    { path: "../fonts/newsreader-latin-300.woff2", weight: "300", style: "normal" },
    { path: "../fonts/newsreader-latin-400.woff2", weight: "400", style: "normal" },
  ],
  variable: "--font-newsreader",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Anril AI", template: "%s | Anril AI" },
  // Live: this site is the homepage, so it is indexed like any public page.
};

// Runs before first paint: turns scroll motion on unless the visitor asked for less, and turns it
// off again if the page script has not confirmed within 5 seconds, so a failed script never leaves
// content hidden.
const MOTION_INIT = `(function(){var s=document.currentScript.parentElement;if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;s.dataset.motion="on";setTimeout(function(){if(!("motionReady" in s.dataset))s.dataset.motion="off"},5000)})()`;

export default function NewSiteLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className={`${newsreader.variable} ${ui.site}`} data-site suppressHydrationWarning>
      <script dangerouslySetInnerHTML={{ __html: MOTION_INIT }} />
      <JsonLd data={ORGANIZATION} />
      <Motion />
      <a href="#main" className={ui.skip}>
        Skip to content
      </a>
      <SiteHeader />
      <main id="main" tabIndex={-1}>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
