/**
 * Horizontal bars as plain HTML: readable without JavaScript, by screen readers (a list with the
 * value as text) and on narrow screens (labels wrap). Bars are decorative; the text carries the
 * number. Rows are shown in the order given (the Python views decide ranking and order).
 */
export type BarRow = {
  key: string;
  label: string;
  /** Bar length as a fraction of the scale (0..1); the caller passes the exported value. */
  share: number | null;
  display: string;
  detail?: string;
  emphasis?: boolean;
};

export function BarList({ rows, scaleMax = 1, label }: { rows: BarRow[]; scaleMax?: number; label: string }) {
  return (
    <ol aria-label={label} className="space-y-2">
      {rows.map((row) => (
        <li key={row.key} className="grid grid-cols-[minmax(4rem,9rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate font-medium" title={row.label}>
            {row.label}
          </span>
          <span className="relative h-3 bg-panel" aria-hidden="true">
            <span
              className={`absolute inset-y-0 left-0 ${row.emphasis ? "bg-accent-red" : "bg-seq-4"}`}
              style={{ width: `${Math.max(0, Math.min(1, (row.share ?? 0) / scaleMax)) * 100}%` }}
            />
          </span>
          <span className="num text-right">
            {row.display}
            {row.detail ? <span className="ml-2 text-xs text-muted-ink">{row.detail}</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Two values per row on one scale (scheduled vs typical, rule vs baseline). */
export function PairedBars({
  rows,
  legend,
  scaleMax,
  label,
}: {
  rows: { key: string; label: string; a: number; aDisplay: string; b: number; bDisplay: string; note?: string }[];
  legend: [string, string];
  scaleMax: number;
  label: string;
}) {
  const width = (v: number) => `${Math.max(0, Math.min(1, v / scaleMax)) * 100}%`;
  return (
    <div>
      <p className="mb-3 flex gap-4 text-xs text-muted-ink" aria-hidden="true">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 bg-rule" /> {legend[0]}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 bg-seq-4" /> {legend[1]}
        </span>
      </p>
      <ol aria-label={label} className="space-y-4">
        {rows.map((row) => (
          <li key={row.key} className="text-sm">
            <p className="font-medium">{row.label}</p>
            {row.note ? <p className="text-xs text-muted-ink">{row.note}</p> : null}
            <div className="mt-1 grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
              <span className="relative h-2.5 bg-panel" aria-hidden="true">
                <span className="absolute inset-y-0 left-0 bg-rule" style={{ width: width(row.a) }} />
              </span>
              <span className="num text-right text-xs">
                <span className="sr-only">{legend[0]}: </span>
                {row.aDisplay}
              </span>
              <span className="relative h-2.5 bg-panel" aria-hidden="true">
                <span className="absolute inset-y-0 left-0 bg-seq-4" style={{ width: width(row.b) }} />
              </span>
              <span className="num text-right text-xs">
                <span className="sr-only">{legend[1]}: </span>
                {row.bDisplay}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
