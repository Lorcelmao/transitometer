"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  Clock,
  Globe,
  Info,
  LayoutGrid,
  ListChecks,
  Map,
  MapPin,
  Menu,
  ShieldCheck,
  SlidersHorizontal,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { NAV, REPOSITORY } from "@/components/site/nav";
import { STREAMLIT_URL } from "@/components/site/site-footer";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

function BrandMark() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5 shrink-0">
      <path d="M2 14 L8 6 L12 11 L18 4" fill="none" stroke="var(--brand)" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="8" cy="6" r="2.2" fill="var(--surface)" stroke="var(--ink)" strokeWidth="1.5" />
      <circle cx="12" cy="11" r="2.2" fill="var(--surface)" stroke="var(--ink)" strokeWidth="1.5" />
    </svg>
  );
}

function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

const PAGE_ICONS: Record<string, typeof LayoutGrid> = {
  "on-time": Clock,
  headways: SlidersHorizontal,
  "missing-trips": ListChecks,
  scorecards: BarChart3,
  stops: MapPin,
  map: Map,
  delay: TrendingUp,
  "early-warning": AlertTriangle,
  "feed-health": Activity,
  validation: ShieldCheck,
  hcmc: Globe,
};

function SidebarLinks({ pathname, inSheet = false }: { pathname: string; inSheet?: boolean }) {
  const wrap = (node: ReactNode) => (inSheet ? <SheetClose asChild>{node}</SheetClose> : node);
  const itemClass = (active: boolean) =>
    `flex min-h-9 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13.5px] no-underline transition-colors ${
      active
        ? "bg-brand-soft font-semibold text-brand"
        : "font-medium text-muted-ink hover:bg-panel hover:text-ink"
    }`;

  return (
    <nav aria-label="Site navigation" className="flex flex-1 flex-col gap-4 px-2.5 py-3">
      <ul className="space-y-0.5">
        <li>
          {wrap(
            <Link
              href="/"
              prefetch={false}
              aria-current={pathname === "/" ? "page" : undefined}
              className={itemClass(pathname === "/")}
            >
              <LayoutGrid className="size-4 shrink-0" aria-hidden="true" />
              <span>Overview</span>
            </Link>,
          )}
        </li>
      </ul>

      {NAV.map((group) => (
        <div key={group.section}>
          <p className="mb-1 px-2.5 text-xs font-semibold text-muted-ink">{group.section}</p>
          <ul className="space-y-0.5">
            {group.links.map((link) => {
              const Icon = PAGE_ICONS[link.page] ?? LayoutGrid;
              const active = pathname === link.href;
              return (
                <li key={link.href}>
                  {wrap(
                    <Link
                      href={link.href}
                      prefetch={false}
                      aria-current={active ? "page" : undefined}
                      className={itemClass(active)}
                    >
                      <Icon className="size-4 shrink-0" aria-hidden="true" />
                      <span className="truncate">{link.label}</span>
                    </Link>,
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div>
        <p className="mb-1 px-2.5 text-xs font-semibold text-muted-ink">Project</p>
        <ul className="space-y-0.5">
          <li>
            {wrap(
              <Link
                href="/about/"
                prefetch={false}
                aria-current={pathname === "/about/" ? "page" : undefined}
                className={itemClass(pathname === "/about/")}
              >
                <Info className="size-4 shrink-0" aria-hidden="true" />
                <span>About project</span>
              </Link>,
            )}
          </li>
        </ul>
      </div>
    </nav>
  );
}

function SidebarFooter() {
  return (
    <div className="space-y-1.5 border-t border-rule px-4 py-3 text-xs text-muted-ink">
      <p className="leading-snug">Public scorecard for riders and reviewers (static snapshot).</p>
      {STREAMLIT_URL ? (
        <a href={STREAMLIT_URL} className="flex min-h-8 items-center gap-2 font-medium text-brand no-underline hover:underline">
          <BarChart3 className="size-3.5 shrink-0" aria-hidden="true" />
          <span>Analyst console (Streamlit)</span>
        </a>
      ) : null}
      <a href={REPOSITORY} className="flex min-h-8 items-center gap-2 font-medium text-brand no-underline hover:underline">
        <GitHubMark className="size-3.5 shrink-0" />
        <span>Source code on GitHub</span>
      </a>
    </div>
  );
}

export function AppShell({
  marker,
  footer,
  children,
}: {
  marker: string;
  footer: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen w-full">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:border-2 focus:border-brand focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-ink focus:no-underline"
      >
        Skip to content
      </a>

      {/* Desktop B1 persistent left sidebar: full-height rail with viewport-pinned sticky content */}
      <aside className="hidden w-[248px] shrink-0 border-r border-rule bg-surface lg:block">
        <div className="sticky top-0 flex h-screen flex-col overflow-y-auto">
          <Link
            href="/"
            prefetch={false}
            className="flex min-h-[58px] shrink-0 items-center gap-2.5 border-b border-rule px-4 text-[17px] font-bold tracking-tight text-ink no-underline"
          >
            <BrandMark />
            <span>Transitometer</span>
          </Link>
          <SidebarLinks pathname={pathname} />
          <SidebarFooter />
        </div>
      </aside>

      {/* Main content column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile header + Sheet navigation drawer */}
        <header className="sticky top-0 z-40 flex min-h-14 items-center justify-between border-b border-rule bg-surface px-4 lg:hidden">
          <Link href="/" prefetch={false} className="flex items-center gap-2 text-base font-bold tracking-tight text-ink no-underline">
            <BrandMark />
            <span>Transitometer</span>
          </Link>
          <Sheet>
            <SheetTrigger asChild>
              <button
                type="button"
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-rule bg-surface text-ink hover:bg-panel"
                aria-label="Open navigation menu"
              >
                <Menu className="size-5" aria-hidden="true" />
              </button>
            </SheetTrigger>
            <SheetContent side="left" className="flex w-[272px] flex-col overflow-y-auto bg-surface p-0">
              <SheetHeader className="border-b border-rule px-4 py-3.5 text-left">
                <SheetTitle className="flex items-center gap-2 text-base font-bold tracking-tight text-ink">
                  <BrandMark />
                  <span>Transitometer</span>
                </SheetTitle>
              </SheetHeader>
              <SidebarLinks pathname={pathname} inSheet />
              <SidebarFooter />
            </SheetContent>
          </Sheet>
        </header>

        {/* Archived-data banner (always visible, zero middots) */}
        <div className="border-b border-rule bg-surface/90 px-4 py-2 md:px-7">
          <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-2">
            <p
              className="inline-flex items-center gap-2 rounded-full border border-rule bg-panel px-3 py-1 text-xs font-medium text-muted-ink"
              data-testid="archived-marker"
            >
              <Clock className="size-3.5 shrink-0 text-brand" aria-hidden="true" />
              <span>{marker}</span>
            </p>
            <div className="hidden items-center gap-4 text-xs text-muted-ink sm:flex">
              <Link href="/data/validation/" prefetch={false} className="font-medium text-brand no-underline hover:underline">
                Validation evidence
              </Link>
              <Link href="/case-study/hcmc/" prefetch={false} className="font-medium text-brand no-underline hover:underline">
                HCMC case study
              </Link>
            </div>
          </div>
        </div>

        <main id="main" className="mx-auto w-full max-w-[1180px] flex-1 px-4 py-6 md:px-7 md:py-7">
          {children}
        </main>
        {footer}
      </div>
    </div>
  );
}
