"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { PAGES } from "@/components/site/nav";
import { PreviewGlyph } from "@/components/story/preview-glyph";

/** Previous and next pages in reading order, like the stops either side on a line diagram. */
export function PageFlow() {
  const pathname = usePathname();
  const index = PAGES.findIndex((p) => p.href === pathname);
  if (index < 0) return null;
  const previous = index > 0 ? PAGES[index - 1] : null;
  const next = index < PAGES.length - 1 ? PAGES[index + 1] : null;
  return (
    <nav aria-label="Previous and next page" className="mt-16 grid gap-4 border-t border-ink pt-6 sm:grid-cols-2">
      {previous ? (
        <Link href={previous.href} className="group flex items-center gap-3 border border-rule p-3 no-underline transition-colors hover:border-ink">
          <ArrowLeft className="size-4 shrink-0 text-muted-ink transition-transform group-hover:-translate-x-0.5" aria-hidden="true" />
          <span>
            <span className="block text-[11px] uppercase tracking-widest text-muted-ink">Previous</span>
            <span className="block text-ink">{previous.label}</span>
          </span>
        </Link>
      ) : (
        <Link href="/" className="group flex items-center gap-3 border border-rule p-3 no-underline transition-colors hover:border-ink">
          <ArrowLeft className="size-4 shrink-0 text-muted-ink" aria-hidden="true" />
          <span>
            <span className="block text-[11px] uppercase tracking-widest text-muted-ink">Back to</span>
            <span className="block text-ink">Overview</span>
          </span>
        </Link>
      )}
      {next ? (
        <Link href={next.href} className="group flex items-center justify-end gap-3 border border-rule p-3 text-right no-underline transition-colors hover:border-ink">
          <span>
            <span className="block text-[11px] uppercase tracking-widest text-muted-ink">Next</span>
            <span className="block text-ink">{next.label}</span>
          </span>
          <PreviewGlyph kind={next.preview} className="hidden h-8 w-12 sm:block" />
          <ArrowRight className="size-4 shrink-0 text-muted-ink transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
      ) : null}
    </nav>
  );
}
