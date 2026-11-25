import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { Markdown } from "@/components/markdown";

/** Compact dashboard page header: muted category breadcrumb, crisp 28px H1, short lead. */
export function PageIntro({
  section,
  title,
  titleId,
  actions,
  children,
}: {
  section: string;
  title: string;
  titleId?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 pb-1 md:flex-row md:items-end md:justify-between md:gap-4">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-muted-ink">{section}</p>
        <h1
          id={titleId}
          className="mt-1 max-w-3xl text-2xl font-bold leading-tight tracking-tight text-ink md:text-[28px]"
        >
          {title}
        </h1>
        <div className="mt-2 max-w-3xl text-[15px] leading-relaxed text-muted-ink">{children}</div>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Shared metric definitions from Python views inside a calm collapsible card (SVG chevron, no ›). */
export function Definitions({ text, lang }: { text: string; lang?: "vi" | "en" }) {
  return (
    <details className="group my-6 rounded-xl border border-rule bg-surface px-4 py-3 shadow-xs md:px-5">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-4 shrink-0 text-muted-ink transition-transform group-open:rotate-90"
          aria-hidden="true"
        />
        <span>How these numbers are defined</span>
      </summary>
      <div className="border-t border-panel pt-3" lang={lang}>
        <Markdown className="max-w-prose text-sm leading-relaxed text-muted-ink">{text}</Markdown>
      </div>
    </details>
  );
}

/** Plain-language attention note (never colour alone; zero middots). */
export function Caveat({ children }: { children: ReactNode }) {
  return (
    <aside
      className="my-5 rounded-lg border border-amber-200 border-l-4 border-l-attention bg-attention-soft px-4 py-3 text-sm leading-relaxed text-ink"
      role="note"
    >
      <span className="font-semibold text-attention-text">Note: </span>
      {children}
    </aside>
  );
}
