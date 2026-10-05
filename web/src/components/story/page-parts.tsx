import type { ReactNode } from "react";

import { Markdown } from "@/components/markdown";

/** Page opening: a section label, the question the page answers, and a short lead. */
export function PageIntro({
  section,
  title,
  titleId,
  children,
}: {
  section: string;
  title: string;
  titleId?: string;
  children: ReactNode;
}) {
  return (
    <header className="pt-10">
      <p className="text-xs font-medium uppercase tracking-widest text-accent-red">{section}</p>
      <h1 id={titleId} className="mt-2 max-w-3xl font-display text-4xl leading-tight md:text-5xl">{title}</h1>
      <div className="mt-4 max-w-prose text-lg text-ink/90">{children}</div>
    </header>
  );
}

/** How the numbers are defined: the shared definitions from the Python views, one click away. */
export function Definitions({ text }: { text: string }) {
  return (
    <details className="group my-10 border-y border-rule py-3">
      <summary className="min-h-11 cursor-pointer list-none py-2 font-medium text-ink">
        <span className="mr-2 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
          ›
        </span>
        How these numbers are defined
      </summary>
      <Markdown className="max-w-prose text-sm leading-relaxed">{text}</Markdown>
    </details>
  );
}

/** A plain-language note that something on the page needs care (never colour alone). */
export function Caveat({ children }: { children: ReactNode }) {
  return (
    <aside className="my-6 border-l-4 border-warn bg-panel px-4 py-3 text-sm" role="note">
      <span className="font-semibold text-warn">Note · </span>
      {children}
    </aside>
  );
}
