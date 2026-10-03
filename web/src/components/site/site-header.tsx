"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV, REPOSITORY } from "@/components/site/nav";
import { PreviewGlyph } from "@/components/story/preview-glyph";
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
} from "@/components/ui/navigation-menu";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

/** Desktop: one dropdown per section, each page with its description and a sketch of its chart. */
function DesktopNav({ pathname }: { pathname: string }) {
  return (
    <NavigationMenu viewport={false} className="hidden lg:flex">
      <NavigationMenuList className="gap-1">
        {NAV.map((group) => {
          const active = group.links.some((l) => l.href === pathname);
          return (
            <NavigationMenuItem key={group.section}>
              <NavigationMenuTrigger
                className={`h-11 rounded-none bg-transparent px-3 text-sm hover:bg-panel data-[state=open]:bg-panel ${active ? "font-semibold underline decoration-accent-red decoration-2 underline-offset-[6px]" : ""}`}
              >
                {group.section}
              </NavigationMenuTrigger>
              <NavigationMenuContent className="rounded-none border border-rule bg-paper p-2 shadow-none">
                <ul className="grid w-[30rem] gap-1">
                  {group.links.map((link) => (
                    <li key={link.href}>
                      <NavigationMenuLink asChild>
                        <Link
                          href={link.href}
                          aria-current={pathname === link.href ? "page" : undefined}
                          className="flex flex-row items-center gap-3 rounded-none p-2 no-underline hover:bg-panel focus:bg-panel"
                        >
                          <PreviewGlyph kind={link.preview} className="size-auto h-9 w-14 shrink-0 border border-rule bg-paper" />
                          <span>
                            <span className={`block text-sm text-ink ${pathname === link.href ? "font-semibold" : "font-medium"}`}>
                              {link.label}
                            </span>
                            <span className="block text-xs text-muted-ink">{link.blurb}</span>
                          </span>
                        </Link>
                      </NavigationMenuLink>
                    </li>
                  ))}
                </ul>
              </NavigationMenuContent>
            </NavigationMenuItem>
          );
        })}
        <NavigationMenuItem>
          <NavigationMenuLink asChild>
            <Link href="/#about" className="inline-flex h-11 items-center px-3 text-sm text-ink no-underline hover:bg-panel">
              About
            </Link>
          </NavigationMenuLink>
        </NavigationMenuItem>
      </NavigationMenuList>
    </NavigationMenu>
  );
}

function MobileNav({ pathname }: { pathname: string }) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        <button type="button" className="flex min-h-11 min-w-11 items-center justify-center lg:hidden" aria-label="Open the site menu">
          <Menu aria-hidden="true" />
        </button>
      </SheetTrigger>
      <SheetContent side="right" className="overflow-y-auto bg-paper">
        <SheetHeader>
          <SheetTitle className="font-display text-xl">Transitometer</SheetTitle>
        </SheetHeader>
        <nav aria-label="Site" className="flex flex-col gap-6 px-4 pb-8">
          <SheetClose asChild>
            <Link href="/" className="text-sm font-medium text-ink no-underline">
              Overview
            </Link>
          </SheetClose>
          {NAV.map((group) => (
            <div key={group.section}>
              <p className="text-[11px] font-medium uppercase tracking-widest text-muted-ink">{group.section}</p>
              <ul className="mt-1">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <SheetClose asChild>
                      <Link
                        href={link.href}
                        aria-current={pathname === link.href ? "page" : undefined}
                        className={`block py-2.5 text-sm no-underline ${pathname === link.href ? "font-semibold text-ink underline decoration-accent-red decoration-2 underline-offset-4" : "text-ink"}`}
                      >
                        {link.label}
                      </Link>
                    </SheetClose>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <SheetClose asChild>
            <Link href="/#about" className="text-sm text-ink no-underline">
              About this project
            </Link>
          </SheetClose>
          <a href={REPOSITORY} className="inline-flex items-center gap-2 text-sm">
            <GitHubMark className="size-4" /> Source on GitHub
          </a>
        </nav>
      </SheetContent>
    </Sheet>
  );
}

export function SiteHeader({ marker }: { marker: string }) {
  const pathname = usePathname();
  return (
    <header className="z-40 border-b border-ink bg-paper/95 backdrop-blur supports-[backdrop-filter]:bg-paper/85 lg:sticky lg:top-0">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:bg-paper focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-1.5 md:px-6">
        <Link href="/" className="flex items-center gap-2 font-display text-2xl font-semibold tracking-tight text-ink no-underline">
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
            <path d="M2 14 L8 6 L12 11 L18 4" fill="none" stroke="var(--link)" strokeWidth="2" />
            <circle cx="8" cy="6" r="2.2" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" />
            <circle cx="12" cy="11" r="2.2" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" />
          </svg>
          Transitometer
        </Link>
        <DesktopNav pathname={pathname} />
        <div className="flex items-center gap-1">
          <a href={REPOSITORY} className="hidden min-h-11 items-center gap-2 px-2 text-sm text-ink no-underline hover:underline md:inline-flex" aria-label="Source code on GitHub">
            <GitHubMark className="size-4" />
            <span className="hidden xl:inline">GitHub</span>
          </a>
          <MobileNav pathname={pathname} />
        </div>
      </div>
      <p className="border-t border-rule px-4 py-1 text-center font-mono text-[11px] text-muted-ink" data-testid="archived-marker">
        {marker}
      </p>
    </header>
  );
}
