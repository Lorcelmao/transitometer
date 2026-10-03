import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import * as format from "@/lib/format";

type Case = { fn: string; args: (number | string | null)[]; expected: string };

// The vectors the Python formatter is tested against (tests/test_serve_views.py).
const CASES: Case[] = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../showcase/contract/format-cases.json"), "utf8"),
);

const IMPLEMENTATIONS: Record<string, (...args: never[]) => string> = {
  pct: format.pct,
  count: format.count,
  minutes: format.minutes,
  decimal: format.decimal,
  score: format.score,
  day_label: format.dayLabel,
  check_value: format.checkValue,
  check_threshold: format.checkThreshold,
};

describe("formatters match Python", () => {
  it("covers every shared function", () => {
    expect(new Set(CASES.map((c) => c.fn))).toEqual(new Set(Object.keys(IMPLEMENTATIONS)));
  });

  it.each(CASES.map((c) => [`${c.fn}(${JSON.stringify(c.args)})`, c] as const))("%s", (_, c) => {
    expect(IMPLEMENTATIONS[c.fn](...(c.args as never[]))).toBe(c.expected);
  });

  it("rounds exact binary ties to even, like Python", () => {
    expect(format.fixed(6.25, 1)).toBe("6.2");
    expect(format.fixed(0.125, 2)).toBe("0.12");
    expect(format.fixed(0.375, 2)).toBe("0.38");
    expect(format.fixed(9.995, 2)).toBe("9.99"); // 9.995 is stored slightly below the tie
    expect(format.fixed(99.95, 1)).toBe("100.0");
  });
});
