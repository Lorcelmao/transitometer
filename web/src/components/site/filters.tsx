"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Meta } from "@/data/schemas";

/** Mode (bus | subway) as a segmented dashboard toggle, labelled for screen readers. */
export function ModeToggle({
  modes,
  value,
  onChange,
}: {
  modes: Meta["modes"];
  value: string;
  onChange: (mode: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span id="mode-label" className="text-[13px] font-medium text-muted-ink">
        Mode
      </span>
      <ToggleGroup
        type="single"
        value={value}
        onValueChange={(v) => v && onChange(v)}
        aria-labelledby="mode-label"
        className="inline-flex rounded-lg border border-rule bg-panel p-0.5"
        spacing={0}
      >
        {modes.map((m) => (
          <ToggleGroupItem
            key={m.key}
            value={m.key}
            className="min-h-10 rounded-md border-0 bg-transparent px-3.5 text-sm font-medium text-muted-ink shadow-none transition-colors hover:text-ink data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs"
            data-testid={`mode-${m.key}`}
          >
            {m.short}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

export function DaySelect({
  days,
  value,
  onChange,
}: {
  days: Meta["days"];
  value: string;
  onChange: (day: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span id="day-label" className="text-[13px] font-medium text-muted-ink">
        Service day
      </span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger
          aria-labelledby="day-label"
          className="min-h-11 rounded-lg border-rule-strong bg-surface text-sm font-medium text-ink"
          data-testid="day-select"
        >
          <SelectValue>{days.find((d) => d.key === value)?.label}</SelectValue>
        </SelectTrigger>
        <SelectContent className="rounded-lg border-rule bg-surface">
          {days.map((d) => (
            <SelectItem key={d.key} value={d.key} data-testid={`day-${d.key}`}>
              {d.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** Sticky desktop filter toolbar (static on mobile so it never eats viewport height). */
export function FilterBar({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="my-5 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-rule bg-surface/95 px-4 py-2.5 shadow-xs backdrop-blur lg:sticky lg:top-0 lg:z-30"
      role="group"
      aria-label="Filters"
    >
      {children}
    </div>
  );
}
