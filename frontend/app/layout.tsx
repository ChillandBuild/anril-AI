import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { Toaster } from "sonner";
import { PwaRegistrar } from "@/components/PwaRegistrar";
import "./globals.css";

// Fonts are self-hosted (latin subset, variable files in app/fonts) instead of
// next/font/google: the Google loader fetches from fonts.googleapis.com at build
// time and crashed the Vercel build when Google returned an unexpected URL shape.
const manrope = localFont({
  src: "./fonts/manrope-latin-var.woff2",
  variable: "--font-manrope",
  display: "swap",
  weight: "200 800",
});

const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin-var.woff2",
  variable: "--font-mono",
  display: "swap",
  weight: "100 800",
});

// Display face for headings and KPI figures. Deliberately NOT wired to the
// shared `font-display` role -- that alias points at Manrope and is used in 76
// component files, so repointing it would restyle most of the app. Opt in per
// page with `font-heading`.
const plusJakarta = localFont({
  src: "./fonts/plus-jakarta-sans-latin-var.woff2",
  variable: "--font-heading",
  display: "swap",
  weight: "200 800",
});

const dancingScript = localFont({
  src: "./fonts/dancing-script-latin-var.woff2",
  variable: "--font-script",
  display: "swap",
  weight: "400 700",
});

export const metadata: Metadata = {
  title: {
    default: "Anril AI – WhatsApp AI Chatbot, CRM & Payments",
    template: "%s | Anril AI",
  },
  metadataBase: new URL("https://www.anrilaitech.com"),
  description:
    "Anril AI replies to every enquiry on WhatsApp, Instagram and Facebook, scores leads, takes payments and tracks calls. Built in Coimbatore.",
  openGraph: { siteName: "Anril AI", type: "website", locale: "en_IN", images: ["/og-image.png"] },
  twitter: { card: "summary_large_image" },
  applicationName: "Anril AI",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Anril AI",
  },
  formatDetection: {
    telephone: false,
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
  icons: {
    icon: [
      { url: "/favicon.ico" },
      { url: "/icons/anril-favicon.svg", type: "image/svg+xml" },
      { url: "/icons/anril-icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: [{ url: "/icons/anril-icon-192.png", sizes: "192x192", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0A1528",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${manrope.variable} ${jetbrainsMono.variable} ${plusJakarta.variable} ${dancingScript.variable}`}>
      <head>
        <link rel="manifest" href="/manifest.webmanifest" crossOrigin="use-credentials" />
      </head>
      <body className="antialiased">
        {children}
        <Toaster position="top-right" richColors closeButton />
        <PwaRegistrar />
      </body>
    </html>
  );
}
