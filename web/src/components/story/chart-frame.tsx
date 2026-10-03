"use client";

import { useId, useState, type ReactNode } from "react";

import { ProvenanceLine } from "@/components/site/provenance-line";
import type { Source } from "@/data/schemas";

export type Column<R> = {
  key: string;
  label: string;
  numeric?: boolean;
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
    <div className="max-h-[32rem] overflow-auto border-y border-rule" tabIndex={0} role="region" aria-label={caption}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-panel">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-ink ${c.numeric ? "text-right" : "text-left"}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-t border-rule/60">
              {columns.map((c, i) =>
                i === 0 ? (
                  <th key={c.key} scope="row" className="px-3 py-1.5 text-left font-medium">
                    {c.render(row)}
                  </th>
                ) : (
                  <td key={c.key} className={`px-3 py-1.5 ${c.numeric ? "num text-right" : ""}`}>
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
 * A chart with its title, a one-sentence reading, a table alternative, a text summary for
 * assistive technology, and the provenance of the numbers.
 */
export function ChartFrame({
  title,
  lead,
  summary,
  chart,
  table,
  source,
  note,
}: {
  title: string;
  lead?: ReactNode;
  summary: string;
  chart: ReactNode;
  table: ReactNode;
  source: Source;
  note?: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const summaryId = useId();
  return (
    <figure className="my-10" aria-describedby={summaryId}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink pb-2">
        <h2 className="font-display text-2xl md:text-3xl">{title}</h2>
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => setAsTable((v) => !v)}
          className="min-h-11 px-2 text-sm text-link underline underline-offset-2"
        >
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {lead ? <div className="mt-3 max-w-prose text-base">{lead}</div> : null}
      <div className="mt-4">{asTable ? table : chart}</div>
      <figcaption className="mt-3 space-y-1 text-sm text-muted-ink">
        <p id={summaryId}>{summary}</p>
        {note ? <div>{note}</div> : null}
        <ProvenanceLine source={source} />
      </figcaption>
    </figure>
  );
}
