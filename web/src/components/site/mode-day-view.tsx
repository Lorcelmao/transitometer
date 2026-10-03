"use client";

import type { ReactNode } from "react";
import type * as z from "zod/mini";

import { DaySelect, FilterBar, ModeToggle } from "@/components/site/filters";
import type { Meta, Source } from "@/data/schemas";
import { useUrlState } from "@/hooks/use-url-state";
import { useView, type Initial } from "@/hooks/use-view";

export type ViewProps<T> = { data: T; source: Source; mode: string; day: string };

function Inner<T>({
  meta,
  page,
  schema,
  initial,
  withDay,
  render,
}: {
  meta: Meta;
  page: string;
  schema: z.ZodMiniType;
  initial: Initial<T>;
  withDay: boolean;
  render: (props: ViewProps<T>) => ReactNode;
}) {
  const modes = meta.modes.map((m) => m.key);
  const days = meta.days.map((d) => d.key);
  const [state, setState] = useUrlState({ mode: modes[0], day: days[0] }, { mode: modes, day: days });
  const file = withDay ? `${page}/${state.mode}-${state.day}.json` : `${page}/${state.mode}.json`;
  const { data, source, pending } = useView<T>(file, schema, initial);
  return (
    <>
      <FilterBar>
        <ModeToggle modes={meta.modes} value={state.mode} onChange={(mode) => setState({ mode })} />
        {withDay ? <DaySelect days={meta.days} value={state.day} onChange={(day) => setState({ day })} /> : null}
        <span aria-live="polite" className="text-xs text-muted-ink">
          {pending ? "Loading…" : ""}
        </span>
      </FilterBar>
      <div className={pending ? "opacity-60 transition-opacity" : "transition-opacity"} data-testid="view">
        {render({ data, source, mode: state.mode, day: state.day })}
      </div>
    </>
  );
}

/**
 * A page section driven by the mode (and day) filters: renders the matching exported view file.
 * `render` receives the validated data; it only lays it out.
 */
export function ModeDayView<T>(props: {
  meta: Meta;
  page: string;
  schema: z.ZodMiniType;
  initial: Initial<T>;
  withDay?: boolean;
  render: (props: ViewProps<T>) => ReactNode;
}) {
  return <Inner {...props} withDay={props.withDay ?? true} />;
}
