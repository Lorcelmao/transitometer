/**
 * Browser-side access to a view file in public/data (per-filter files and stop routes), with the
 * same schema validation as the build. Responses are cached per URL for the session.
 */
import type * as z from "zod/mini";

import { parseView, type Source } from "@/data/schemas";

const cache = new Map<string, Promise<unknown>>();

export async function fetchView<T extends z.ZodMiniType>(
  file: string,
  schema: T,
): Promise<{ data: z.infer<T>; source: Source }> {
  const url = `/data/${file}`;
  if (!cache.has(url)) {
    cache.set(
      url,
      fetch(url).then((response) => {
        if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
        return response.json();
      }),
    );
  }
  let body: unknown;
  try {
    body = await cache.get(url);
  } catch (error) {
    cache.delete(url); // let a later attempt retry a failed request
    throw error;
  }
  return parseView(url, body, schema);
}
