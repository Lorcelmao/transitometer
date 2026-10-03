"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Meta } from "@/data/schemas";

/** Mode (bus | subway) as a toggle group, labelled for screen readers. */
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
      <span id="mode-label" className="text-xs font-medium uppercase tracking-widest text-muted-ink">
        Mode
      </span>
      <ToggleGroup
        type="single"
        value={value}
        onValueChange={(v) => v && onChange(v)}
        aria-labelledby="mode-label"
        variant="outline"
        spacing={0}
      >
        {modes.map((m) => (
          <ToggleGroupItem
            key={m.key}
            value={m.key}
            className="min-h-11 rounded-none px-4 data-[state=on]:bg-ink data-[state=on]:text-paper"
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
      <span id="day-label" className="text-xs font-medium uppercase tracking-widest text-muted-ink">
        Service day
      </span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-labelledby="day-label" className="min-h-11 rounded-none bg-paper" data-testid="day-select">
          {/* The label is rendered in the static HTML too, so the control does not change size
              (and shift the page) when it hydrates. */}
          <SelectValue>{days.find((d) => d.key === value)?.label}</SelectValue>
        </SelectTrigger>
        <SelectContent>
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

/** The filters of a page, in one row above its content. */
export function FilterBar({ children }: { children: React.ReactNode }) {
  return (
    <div className="my-6 flex flex-wrap items-center gap-x-8 gap-y-3 border-y border-rule py-3" role="group" aria-label="Filters">
      {children}
    </div>
  );
}
