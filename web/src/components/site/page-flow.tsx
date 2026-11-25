"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PAGES } from "@/components/site/nav";

/** Previous and next pages in reading order, as clean dashboard footer links (no arrow icons). */
export function PageFlow() {
  const pathname = usePathname();
  const index = PAGES.findIndex((p) => p.href === pathname);
  if (index < 0) return null;
  const previous = index > 0 ? PAGES[index - 1] : null;
  const next = index < PAGES.length - 1 ? PAGES[index + 1] : null;
  return (
    <nav
      aria-label="Previous and next page"
      className="mt-12 grid gap-3 border-t border-rule pt-5 sm:grid-cols-2"
    >
      {previous ? (
        <Link
          href={previous.href}
          prefetch={false}
          className="flex flex-col rounded-lg border border-rule bg-surface px-4 py-3 no-underline transition-colors hover:border-brand hover:bg-brand-soft/40"
        >
          <span className="text-xs font-medium text-muted-ink">Previous page</span>
          <span className="mt-0.5 text-sm font-semibold text-ink">{previous.label}</span>
        </Link>
      ) : (
        <Link
          href="/"
          prefetch={false}
          className="flex flex-col rounded-lg border border-rule bg-surface px-4 py-3 no-underline transition-colors hover:border-brand hover:bg-brand-soft/40"
        >
          <span className="text-xs font-medium text-muted-ink">Back to</span>
          <span className="mt-0.5 text-sm font-semibold text-ink">Overview</span>
        </Link>
      )}
      {next ? (
        <Link
          href={next.href}
          prefetch={false}
          className="flex flex-col rounded-lg border border-rule bg-surface px-4 py-3 text-right no-underline transition-colors hover:border-brand hover:bg-brand-soft/40"
        >
          <span className="text-xs font-medium text-muted-ink">Next page</span>
          <span className="mt-0.5 text-sm font-semibold text-ink">{next.label}</span>
        </Link>
      ) : null}
    </nav>
  );
}
