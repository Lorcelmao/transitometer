import type { Figure } from "@/data/schemas";

/** A headline number: the display string computed in Python, its label and its definition. */
export function KpiFigure({ figure, size = "lg" }: { figure: Figure; size?: "lg" | "md" }) {
  return (
    <div className="border-t-2 border-ink pt-2" data-testid={`figure-${figure.key}`}>
      <dt className="text-xs font-medium uppercase tracking-wider text-muted-ink">{figure.label}</dt>
      <dd
        className={`num mt-1 leading-none text-ink ${size === "lg" ? "text-4xl xl:text-5xl" : "text-2xl md:text-3xl"}`}
        data-testid={`value-${figure.key}`}
      >
        {figure.display}
      </dd>
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
