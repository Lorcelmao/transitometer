"use client";

import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Figure } from "@/data/schemas";

export type KpiBadgeTone = "pass" | "fail" | "attention" | "neutral";

const BADGE_STYLES: Record<KpiBadgeTone, string> = {
  pass: "bg-pass-soft text-pass-text",
  fail: "bg-fail-soft text-fail-text",
  attention: "bg-attention-soft text-attention-text",
  neutral: "bg-panel text-muted-ink",
};

export type KpiExtra = {
  badge?: { label: string; tone: KpiBadgeTone };
  viz?: ReactNode;
  /** Short single-line plain-English description displayed in the card (full technical help stays in tooltip). */
  shortNote?: string;
};

function conciseSummary(help: string | null): string | null {
  if (!help) return null;
  const firstSentence = help.split(/(?<=[.!?])\s+/)[0] ?? help;
  return firstSentence.length <= 95 ? firstSentence : `${firstSentence.slice(0, 92).trimEnd()}...`;
}

/**
 * Dashboard KPI card following the 4-step reading order:
 * 1. Short label (+ accessible tooltip button for full technical definition)
 * 2. Primary value (+ optional semantic status badge)
 * 3. Optional real-data micro-visual
 * 4. One short plain-English note (full help stays in tooltip so cards never turn into essays)
 */
export function KpiFigure({
  figure,
  size = "lg",
  extra,
}: {
  figure: Figure;
  size?: "lg" | "md";
  extra?: KpiExtra;
}) {
  const visibleNote = extra?.shortNote ?? figure.basis ?? conciseSummary(figure.help);
  const showTooltip = Boolean(figure.help);

  return (
    <div
      className="flex flex-col gap-1.5 rounded-xl border border-rule bg-surface p-4 shadow-xs"
      data-testid={`figure-${figure.key}`}
    >
      <dt className="flex items-start justify-between gap-2 text-[13px] font-semibold leading-snug text-muted-ink">
        <span>{figure.label}</span>
        {showTooltip ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`Definition of ${figure.label}`}
                className="relative inline-flex size-6 shrink-0 items-center justify-center rounded-full border border-rule bg-paper text-xs font-semibold text-muted-ink transition-colors hover:border-brand hover:text-brand after:absolute after:-inset-2.5 after:content-['']"
              >
                ?
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs rounded-lg border border-rule bg-surface px-3 py-2 text-xs leading-relaxed text-ink shadow-md">
              {figure.help}
            </TooltipContent>
          </Tooltip>
        ) : null}
      </dt>

      <dd className="flex flex-wrap items-baseline justify-between gap-2">
        <span
          key={figure.display}
          className={`num value-update font-bold leading-tight tracking-tight text-ink ${
            size === "lg" ? "text-[28px] xl:text-[30px]" : "text-2xl"
          }`}
          data-testid={`value-${figure.key}`}
        >
          {figure.display}
        </span>
        {extra?.badge ? (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE_STYLES[extra.badge.tone]}`}
          >
            {extra.badge.label}
          </span>
        ) : null}
      </dd>

      {extra?.viz ? <dd className="my-1">{extra.viz}</dd> : null}

      {visibleNote ? (
        <dd className="text-xs leading-relaxed text-muted-ink">{visibleNote}</dd>
      ) : null}

      {figure.basis ? (
        <dd className="sr-only" data-testid={`basis-${figure.key}`}>
          {figure.basis}
        </dd>
      ) : null}
    </div>
  );
}

/** Responsive KPI grid that adapts cleanly to 1, 2, 3, 4, or 5 metrics without orphan cards. */
export function KpiRow({
  figures,
  size,
  extras,
}: {
  figures: Figure[];
  size?: "lg" | "md";
  extras?: Record<string, KpiExtra>;
}) {
  const cols =
    figures.length <= 1
      ? "grid-cols-1 max-w-md"
      : figures.length === 2
        ? "grid-cols-1 sm:grid-cols-2"
        : figures.length === 3
          ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
          : figures.length === 4
            ? "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4"
            : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5";

  return (
    <dl className={`grid gap-3.5 ${cols}`}>
      {figures.map((f) => (
        <KpiFigure key={f.key} figure={f} size={size} extra={extras?.[f.key]} />
      ))}
    </dl>
  );
}
