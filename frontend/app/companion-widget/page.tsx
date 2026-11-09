import type { Metadata } from "next";
import { Suspense } from "react";
import CompanionChat from "./CompanionChat";

// The chat window inside the companion widget's iframe (public/companion-widget.js opens it on
// the business's site). No login: the business's server signs the user id; this page gets it
// from the parent page by postMessage and sends it with every call.
export const metadata: Metadata = { title: "Chat", robots: { index: false, follow: false } };

export default function CompanionWidgetPage() {
  return (
    <Suspense fallback={null}>
      <CompanionChat />
    </Suspense>
  );
}
