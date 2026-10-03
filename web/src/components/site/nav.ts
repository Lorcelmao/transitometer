/**
 * Site sections and pages, in reading order. Routes equal the export's page routes (meta.json;
 * checked in tests). The header menus, the overview's explore cards and the previous/next links
 * at the foot of each page all read this one list.
 */
export type Preview = "heatmap" | "bars" | "outcomes" | "intervals" | "hours" | "map" | "split" | "verdict" | "checks" | "evidence";

export const NAV = [
  {
    section: "Reliability",
    links: [
      { page: "on-time", href: "/reliability/on-time/", label: "On-time performance", blurb: "Which routes reach their stops on schedule, hour by hour.", preview: "heatmap" },
      { page: "headways", href: "/reliability/headways/", label: "Headways and bunching", blurb: "Where vehicles arrive in clumps and leave long gaps behind.", preview: "bars" },
      { page: "missing-trips", href: "/reliability/missing-trips/", label: "Trip delivery", blurb: "Which scheduled trips the feed never showed running.", preview: "outcomes" },
    ],
  },
  {
    section: "Diagnostics",
    links: [
      { page: "scorecards", href: "/diagnostics/route-scorecards/", label: "Route scorecards", blurb: "Route rankings with honest confidence intervals.", preview: "intervals" },
      { page: "stops", href: "/diagnostics/stops/", label: "Stop reliability", blurb: "How dependable a route is at your stop, by hour.", preview: "hours" },
      { page: "map", href: "/diagnostics/map/", label: "Stop map", blurb: "Every stop in the city, coloured by how often it was on time.", preview: "map" },
      { page: "delay", href: "/diagnostics/delay/", label: "Where delay builds up", blurb: "Whether late trips started late or lost time on the way.", preview: "split" },
      { page: "early-warning", href: "/diagnostics/early-warning/", label: "Early warning", blurb: "Could trouble be predicted halfway through a trip?", preview: "verdict" },
    ],
  },
  {
    section: "Data quality",
    links: [
      { page: "feed-health", href: "/data/feed-health/", label: "Feed health", blurb: "How trustworthy the real-time feeds themselves are.", preview: "checks" },
      { page: "validation", href: "/data/validation/", label: "Data & validation", blurb: "The evidence behind every number on this site.", preview: "evidence" },
    ],
  },
] as const satisfies readonly { section: string; links: readonly { page: string; href: string; label: string; blurb: string; preview: Preview }[] }[];

export type NavLink = (typeof NAV)[number]["links"][number];

/** Every page in reading order (for previous/next links). */
export const PAGES: readonly NavLink[] = NAV.flatMap((group): readonly NavLink[] => group.links);

export const REPOSITORY = "https://github.com/Lorcelmao/transitometer";
