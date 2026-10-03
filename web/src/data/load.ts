/**
 * Build-time data access: reads the committed JSON in public/data and validates it.
 *
 * Only Server Components call these (they run during `next build` for a static export), so a
 * missing file or a contract mismatch fails the build with the file name in the error.
 */
import fs from "node:fs";
import path from "node:path";

import type * as z from "zod/mini";

import { meta as metaSchema, parseView, type Meta, type Source } from "@/data/schemas";

const DATA = path.join(process.cwd(), "public", "data");

function readJson(file: string): unknown {
  const full = path.join(DATA, file);
  if (!fs.existsSync(full)) {
    throw new Error(`public/data/${file} is missing; run \`python tasks.py web-data\``);
  }
  return JSON.parse(fs.readFileSync(full, "utf8"));
}

/** One exported view: its data and its provenance (tables, snapshot commit, date). */
export function readView<T extends z.ZodMiniType>(
  file: string,
  schema: T,
): { data: z.infer<T>; source: Source } {
  return parseView(`public/data/${file}`, readJson(file), schema);
}

let cachedMeta: Meta | undefined;

/** Site-wide facts: snapshot provenance, modes, days and page routes. */
export function readMeta(): Meta {
  if (!cachedMeta) {
    cachedMeta = readView("meta.json", metaSchema).data;
  }
  return cachedMeta;
}
