"use client";

/**
 * The view file for the current filters. The default filters' file is rendered into the static
 * HTML (`initial`); another combination is fetched from public/data when chosen, while the
 * previous view stays on screen (useDeferredValue) and is marked as pending.
 */
import { use, useDeferredValue } from "react";
import type * as z from "zod/mini";

import { fetchView } from "@/data/fetch-view";
import type { Source } from "@/data/schemas";

export type Loaded<T> = { data: T; source: Source };
export type Initial<T> = Loaded<T> & { file: string };

const promises = new Map<string, Promise<unknown>>();

function viewPromise<T>(file: string, schema: z.ZodMiniType): Promise<Loaded<T>> {
  if (!promises.has(file)) promises.set(file, fetchView(file, schema));
  return promises.get(file) as Promise<Loaded<T>>;
}

export function useView<T>(
  file: string,
  schema: z.ZodMiniType,
  initial: Initial<T>,
): Loaded<T> & { pending: boolean } {
  const shown = useDeferredValue(file, initial.file);
  const loaded = shown === initial.file ? initial : use(viewPromise<T>(shown, schema));
  return { data: loaded.data, source: loaded.source, pending: shown !== file };
}
