import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Newsreader } from "next/font/google";

import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { TooltipProvider } from "@/components/ui/tooltip";
import { readMeta } from "@/data/load";

import "./globals.css";

// Self-hosted at build time by next/font: the site makes no font request to Google at runtime.
const display = Newsreader({ subsets: ["latin"], variable: "--font-newsreader", display: "optional" });
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "optional",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "optional",
});

export const metadata: Metadata = {
  title: { default: "Transitometer · was the promised transit service delivered?", template: "%s · Transitometer" },
  description:
    "Bus and subway reliability in New York, measured from two days of real archived GTFS-Realtime feeds by a Kafka, Spark and Delta Lake pipeline, and checked against an independent reference.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const meta = readMeta();
  const days = meta.days.map((d) => d.label);
  const marker = `Archived data · ${days.join(" and ")} · not a live service`;
  return (
    // The intro animation plays once per browser session: this runs before first paint and marks
    // later page loads as "seen" (the attribute differs from the server HTML on purpose).
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var s=window.sessionStorage;if(s.getItem('tm-intro'))document.documentElement.dataset.intro='seen';else s.setItem('tm-intro','1')}catch(e){}",
          }}
        />
      </head>
      <body className="flex min-h-screen flex-col">
        <TooltipProvider>
          <SiteHeader marker={marker} />
          <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 md:px-6">
            {children}
          </main>
          <SiteFooter meta={meta} />
        </TooltipProvider>
      </body>
    </html>
  );
}
