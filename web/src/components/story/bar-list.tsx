/**
 * Horizontal bars as plain HTML: readable without JavaScript, by screen readers (a list with the
 * value as text) and on narrow screens (labels wrap). Bars are decorative; the text carries the
 * number. Rows are shown in the order given (the Python views decide ranking and order).
 */
function fraction(value: number, scaleMax: number): number {
  return scaleMax > 0 ? Math.max(0, Math.min(1, value / scaleMax)) : 0;
}

export type BarRow = {
  key: string;
  label: string;
  share: number | null;
  display: string;
  detail?: string;
  emphasis?: boolean;
};

export function BarList({ rows, scaleMax = 1, label }: { rows: BarRow[]; scaleMax?: number; label: string }) {
  return (
    <ol
      aria-label={label}
      className="grid grid-cols-[minmax(3.5rem,7.5rem)_1fr_auto] gap-x-3 gap-y-2 sm:grid-cols-[minmax(4.5rem,12.5rem)_1fr_auto]"
    >
      {rows.map((row) => (
        <li
          key={row.key}
          className="col-span-3 grid grid-cols-subgrid items-center rounded-md px-1 py-1 text-sm transition-colors hover:bg-paper"
        >
          <span className="truncate font-semibold leading-tight text-ink" title={row.label}>
            {row.label}
          </span>
          <span className="relative h-2.5 overflow-hidden rounded-full bg-panel" aria-hidden="true">
            <span
              className={`absolute inset-0 origin-left rounded-full transition-transform duration-300 ease-out motion-reduce:transition-none ${
                row.emphasis ? "bg-fail" : "bg-seq-4"
              }`}
              style={{ transform: `scaleX(${fraction(row.share ?? 0, scaleMax)})` }}
            />
          </span>
          <span className="num text-right text-sm font-medium text-ink">
            {row.display}
            {row.detail ? (
              <span className="ml-2 hidden text-xs font-normal text-muted-ink sm:inline">{row.detail}</span>
            ) : null}
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
  const bar = (v: number) => ({ transform: `scaleX(${fraction(v, scaleMax)})` });
  const fill =
    "absolute inset-0 origin-left rounded-full transition-transform duration-300 ease-out motion-reduce:transition-none";
  return (
    <div>
      <p className="mb-3 flex flex-wrap gap-4 text-xs font-medium text-muted-ink" aria-hidden="true">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-full bg-rule-strong" /> {legend[0]}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-full bg-seq-4" /> {legend[1]}
        </span>
      </p>
      <ol aria-label={label} className="space-y-4">
        {rows.map((row) => (
          <li key={row.key} className="text-sm">
            <p className="font-semibold text-ink">{row.label}</p>
            {row.note ? <p className="text-xs text-muted-ink">{row.note}</p> : null}
            <div className="mt-1.5 grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5">
              <span className="relative h-2.5 overflow-hidden rounded-full bg-panel" aria-hidden="true">
                <span className={`${fill} bg-rule-strong`} style={bar(row.a)} />
              </span>
              <span className="num text-right text-xs font-medium text-muted-ink">
                <span className="sr-only">{legend[0]}: </span>
                {row.aDisplay}
              </span>
              <span className="relative h-2.5 overflow-hidden rounded-full bg-panel" aria-hidden="true">
                <span className={`${fill} bg-seq-4`} style={bar(row.b)} />
              </span>
              <span className="num text-right text-xs font-semibold text-ink">
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
