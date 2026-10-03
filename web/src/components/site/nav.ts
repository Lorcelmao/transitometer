/** Site sections and pages. Routes equal the export's page routes (meta.json; checked in tests). */
export const NAV = [
  {
    section: "Reliability",
    links: [
      { page: "on-time", href: "/reliability/on-time/", label: "On-time performance" },
      { page: "headways", href: "/reliability/headways/", label: "Headways and bunching" },
      { page: "missing-trips", href: "/reliability/missing-trips/", label: "Missing trips" },
    ],
  },
  {
    section: "Diagnostics",
    links: [
      { page: "scorecards", href: "/diagnostics/route-scorecards/", label: "Route scorecards" },
      { page: "stops", href: "/diagnostics/stops/", label: "Stop reliability" },
      { page: "map", href: "/diagnostics/map/", label: "Stop map" },
      { page: "delay", href: "/diagnostics/delay/", label: "Where delay builds up" },
      { page: "early-warning", href: "/diagnostics/early-warning/", label: "Early warning" },
    ],
  },
  {
    section: "Data quality",
    links: [
      { page: "feed-health", href: "/data/feed-health/", label: "Feed health" },
      { page: "validation", href: "/data/validation/", label: "Data & validation" },
    ],
  },
] as const;
