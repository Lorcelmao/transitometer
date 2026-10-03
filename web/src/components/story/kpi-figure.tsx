import type { Figure } from "@/data/schemas";

/**
 * A headline number: the display string computed in Python, its label, the sample it rests on
 * and its definition. The value is keyed by its text, so a filter change replays a short
 * crossfade (.value-update) instead of swapping silently.
 */
export function KpiFigure({ figure, size = "lg" }: { figure: Figure; size?: "lg" | "md" }) {
  return (
    <div className="border-t-2 border-ink pt-2" data-testid={`figure-${figure.key}`}>
      <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">{figure.label}</dt>
      <dd
        key={figure.display}
        className={`num value-update mt-1 leading-none text-ink ${size === "lg" ? "text-4xl xl:text-5xl" : "text-2xl md:text-3xl"}`}
        data-testid={`value-${figure.key}`}
      >
        {figure.display}
      </dd>
      {figure.basis ? (
        <dd className="mt-1 font-mono text-xs text-muted-ink" data-testid={`basis-${figure.key}`}>
          {figure.basis}
        </dd>
      ) : null}
      {figure.help ? <dd className="mt-2 max-w-prose text-sm text-muted-ink">{figure.help}</dd> : null}
    </div>
  );
}

export function KpiRow({ figures, size }: { figures: Figure[]; size?: "lg" | "md" }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
      {figures.map((f) => (
        <KpiFigure key={f.key} figure={f} size={size} />
      ))}
    </dl>
  );
}
