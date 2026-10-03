"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV } from "@/components/site/nav";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      {NAV.map((group) => (
        <div key={group.section} className="flex flex-col gap-1 lg:flex-row lg:items-baseline lg:gap-3">
          <span className="whitespace-nowrap text-[11px] font-medium uppercase tracking-widest text-muted-ink">{group.section}</span>
          <ul className="flex flex-col gap-1 lg:flex-row lg:gap-3">
            {group.links.map((link) => {
              const current = pathname === link.href;
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    onClick={onNavigate}
                    aria-current={current ? "page" : undefined}
                    className={`inline-block whitespace-nowrap py-2 text-sm no-underline lg:py-1 ${current ? "font-semibold text-ink underline decoration-accent-red decoration-2 underline-offset-4" : "text-ink hover:underline"}`}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </>
  );
}

export function SiteHeader({ marker }: { marker: string }) {
  return (
    <header className="border-b border-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:bg-paper focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 md:px-6">
        <Link href="/" className="font-display text-2xl font-semibold tracking-tight text-ink no-underline">
          Transitometer
        </Link>
        <p className="hidden font-mono text-xs text-muted-ink md:block" data-testid="archived-marker">
          {marker}
        </p>
        <Sheet>
          <SheetTrigger asChild>
            <button
              type="button"
              className="flex min-h-11 min-w-11 items-center justify-center lg:hidden"
              aria-label="Open the site menu"
            >
              <Menu aria-hidden="true" />
            </button>
          </SheetTrigger>
          <SheetContent side="right" className="bg-paper">
            <SheetHeader>
              <SheetTitle className="font-display text-xl">Transitometer</SheetTitle>
            </SheetHeader>
            <nav aria-label="Site" className="flex flex-col gap-5 px-4">
              <NavLinks />
            </nav>
          </SheetContent>
        </Sheet>
      </div>
      <nav aria-label="Site" className="mx-auto hidden max-w-6xl flex-wrap gap-x-8 gap-y-1 px-4 pb-2 md:px-6 lg:flex">
        <NavLinks />
      </nav>
      <p className="border-t border-rule px-4 py-1 text-center font-mono text-xs text-muted-ink md:hidden">{marker}</p>
    </header>
  );
}
