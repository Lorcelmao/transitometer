"use client";

import { Check, ChevronsUpDown } from "lucide-react";
import { useId, useState } from "react";

import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export type Option = { value: string; label: string };

/** A labelled, searchable single choice (route, stop): keyboard type-ahead, screen-reader listbox. */
export function SearchSelect({
  label,
  options,
  value,
  onChange,
  placeholder,
  testId,
}: {
  label: string;
  options: Option[];
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  testId: string;
}) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  const listId = useId();
  const current = options.find((o) => o.value === value);
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span id={labelId} className="text-xs font-medium uppercase tracking-widest text-muted-ink">
        {label}
      </span>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-labelledby={labelId}
            data-testid={testId}
            className="flex min-h-11 w-full min-w-56 max-w-md items-center justify-between gap-2 border border-rule bg-paper px-3 text-left text-sm"
          >
            <span className="truncate">{current?.label ?? placeholder}</span>
            <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden="true" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-[min(28rem,calc(100vw-2rem))] rounded-none p-0" align="start">
          <Command>
            <CommandInput placeholder={placeholder} aria-label={`Search ${label.toLowerCase()}`} />
            <CommandList id={listId}>
              <CommandEmpty>No match.</CommandEmpty>
              <CommandGroup>
                {options.map((o) => (
                  <CommandItem
                    key={o.value}
                    value={`${o.label} ${o.value}`}
                    onSelect={() => {
                      onChange(o.value);
                      setOpen(false);
                    }}
                  >
                    <Check className={`size-4 ${o.value === value ? "opacity-100" : "opacity-0"}`} aria-hidden="true" />
                    {o.label}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
