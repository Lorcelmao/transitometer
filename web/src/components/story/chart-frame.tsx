"use client";

import { useId, useState, type ReactNode } from "react";

import { ProvenanceLine } from "@/components/site/provenance-line";
import type { Source } from "@/data/schemas";

export type Column<R> = {
  key: string;
  label: string;
  numeric?: boolean;
  lang?: "vi" | "en";
  render: (row: R) => ReactNode;
};

/** Every row of a chart as an accessible table (the chart's alternative view). */
export function DataTable<R>({
  rows,
  columns,
  caption,
  rowKey,
}: {
  rows: R[];
  columns: Column<R>[];
  caption: string;
  rowKey: (row: R) => string;
}) {
  return (
    // Focusable so keyboard users can scroll it (WCAG 2.1.1); named after the table it holds.
    <div
      className="max-h-[30rem] max-w-full overflow-auto rounded-lg border border-rule bg-surface"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-paper">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`border-b border-rule px-3 py-2 text-xs font-semibold text-muted-ink ${
                  c.numeric ? "text-right" : "text-left"
                }`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-t border-panel transition-colors hover:bg-paper/70">
              {columns.map((c, i) =>
                i === 0 ? (
                  <th
                    key={c.key}
                    scope="row"
                    lang={c.lang}
                    className="px-3 py-2 text-left font-medium text-ink"
                  >
                    {c.render(row)}
                  </th>
                ) : (
                  <td
                    key={c.key}
                    lang={c.lang}
                    className={`px-3 py-2 ${c.numeric ? "num text-right text-ink" : "text-ink"}`}
                  >
                    {c.render(row)}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Dashboard chart card: title, concise reading lead, chart/table toggle, summary and compact
 * provenance footer.
 */
export function ChartFrame({
  title,
  lead,
  summary,
  chart,
  table,
  source,
  provenance,
  note,
  className = "my-6",
}: {
  title: string;
  lead?: ReactNode;
  summary: string;
  chart: ReactNode;
  table: ReactNode;
  source?: Source;
  provenance?: ReactNode;
  note?: ReactNode;
  className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const summaryId = useId();
  return (
    <figure
      className={`overflow-hidden rounded-xl border border-rule bg-surface shadow-xs ${className}`}
      aria-describedby={summaryId}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-panel px-4 py-3.5 md:px-5">
        <div className="min-w-0 flex-1">
          <h2 className="text-[17px] font-semibold leading-snug text-ink">{title}</h2>
          {lead ? <div className="mt-1 text-sm text-muted-ink">{lead}</div> : null}
        </div>
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => setAsTable((v) => !v)}
          className="inline-flex min-h-10 shrink-0 items-center rounded-md border border-rule bg-paper px-3 text-xs font-semibold text-brand transition-colors hover:bg-brand-soft"
        >
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      <div className="p-4 md:p-5">{asTable ? table : chart}</div>
      <figcaption className="space-y-1.5 border-t border-rule bg-paper px-4 py-3 text-xs text-muted-ink md:px-5">
        <p id={summaryId}>{summary}</p>
        {note ? <div>{note}</div> : null}
        {provenance ?? (source ? <ProvenanceLine source={source} /> : null)}
      </figcaption>
    </figure>
  );
}
