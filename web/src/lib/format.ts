/**
 * Display formatting for chart axes and tooltips, identical to src/transitometer/serve/format.py.
 *
 * Headline figures arrive pre-formatted from Python; these functions only format values the
 * charts show on hover or on an axis. They follow Python's rules exactly, including rounding an
 * exact binary tie to even (Python) rather than up (JavaScript's toFixed), and are tested against
 * the same vectors as the Python formatter (showcase/contract/format-cases.json).
 */

export const MISSING = "—";

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value);
}

/** Python's format(x, `.{digits}f`): round the exact binary value, ties to even. */
export function fixed(value: number, digits: number): string {
  const negative = value < 0 || Object.is(value, -0);
  const exact = Math.abs(value).toFixed(100); // exact decimal expansion of the double
  const [whole, fraction] = exact.split(".");
  const kept = whole + fraction.slice(0, digits);
  const rest = fraction.slice(digits);
  const last = Number(kept[kept.length - 1]);
  const roundUp =
    rest[0] > "5" || (rest[0] === "5" && (/[1-9]/.test(rest.slice(1)) || last % 2 === 1));
  let digitsOut = kept;
  if (roundUp) {
    const chars = kept.split("");
    let i = chars.length - 1;
    while (i >= 0 && chars[i] === "9") chars[i--] = "0";
    if (i < 0) chars.unshift("1");
    else chars[i] = String(Number(chars[i]) + 1);
    digitsOut = chars.join("");
  }
  const intPart = digitsOut.slice(0, digitsOut.length - digits) || "0";
  const fracPart = digits > 0 ? `.${digitsOut.slice(digitsOut.length - digits)}` : "";
  return `${negative ? "-" : ""}${intPart.replace(/^0+(?=\d)/, "")}${fracPart}`;
}

function grouped(text: string): string {
  const [intPart, fracPart] = text.split(".");
  const sign = intPart.startsWith("-") ? "-" : "";
  const digits = intPart.replace("-", "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${digits}${fracPart !== undefined ? `.${fracPart}` : ""}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  return isMissing(value) ? MISSING : `${fixed(100 * value, digits)} %`;
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? MISSING : grouped(String(Math.trunc(value)));
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** '20260922' -> 'Tue 22 Sep 2026'. */
export function dayLabel(day: string): string {
  const date = new Date(Date.UTC(Number(day.slice(0, 4)), Number(day.slice(4, 6)) - 1, Number(day.slice(6))));
  return `${WEEKDAYS[date.getUTCDay()]} ${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

export function minutes(seconds: number | null | undefined): string {
  if (isMissing(seconds)) return MISSING;
  const sign = seconds < 0 ? "−" : "";
  return `${sign}${fixed(Math.abs(seconds) / 60, 1)} min`;
}

export function score(value: number | null | undefined): string {
  return isMissing(value) ? MISSING : `${fixed(value, 1)} / 100`;
}

export function decimal(value: number | null | undefined, digits = 2): string {
  return isMissing(value) ? MISSING : fixed(value, digits);
}

export function checkValue(value: number | null | undefined, unit: string): string {
  if (isMissing(value)) return "no data";
  return unit === "%" ? pct(value, 2) : `${grouped(fixed(value, 1))} s`;
}

export function checkThreshold(threshold: number, unit: string): string {
  return unit === "%" ? `≤ ${pct(threshold, 2)}` : `≤ ${grouped(fixed(threshold, 0))} s`;
}

/** Seconds as shown in tooltips (whole seconds, grouped). */
export function seconds(value: number | null | undefined): string {
  return isMissing(value) ? MISSING : `${grouped(fixed(value, 0))} s`;
}
