import type { Metadata } from "next";
import { Atkinson_Hyperlegible_Next, Be_Vietnam_Pro } from "next/font/google";

import { AppShell } from "@/components/site/site-header";
import { SiteFooter } from "@/components/site/site-footer";
import { TooltipProvider } from "@/components/ui/tooltip";
import { readMeta } from "@/data/load";

import "./globals.css";

// Self-hosted at build time by next/font: zero external font requests at runtime.
// Atkinson Hyperlegible Next powers the English dashboard UI; Be Vietnam Pro renders any
// lang="vi" element cleanly with full Vietnamese diacritics (no cross-font glyph mixing).
const atkinson = Atkinson_Hyperlegible_Next({
  subsets: ["latin"],
  variable: "--font-atkinson",
  display: "swap",
});

const beVietnam = Be_Vietnam_Pro({
  subsets: ["vietnamese", "latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-be-vietnam",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: { default: "Transitometer: NYC bus and subway reliability", template: "%s | Transitometer" },
  description:
    "Bus and subway reliability in New York, measured from two days of real archived GTFS-Realtime feeds by a Kafka, Spark and Delta Lake pipeline, and checked against an independent reference.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const meta = readMeta();
  const days = meta.days.map((d) => d.label);
  const marker = `Archived data for ${days.join(" and ")} (not a live service)`;
  return (
    <html lang="en" className={`${atkinson.variable} ${beVietnam.variable}`} suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var s=window.sessionStorage;if(s.getItem('tm-intro'))document.documentElement.dataset.intro='seen';else s.setItem('tm-intro','1')}catch(e){}",
          }}
        />
      </head>
      <body className="min-h-screen bg-paper text-ink">
        <TooltipProvider delayDuration={150}>
          <AppShell marker={marker} footer={<SiteFooter meta={meta} />}>
            {children}
          </AppShell>
        </TooltipProvider>
      </body>
    </html>
  );
}
