/** Column order for stop-map stop tuples (shared with Python web_export.MAP_COLUMNS). */
export const MAP_COLUMNS = [
  "stop_id",
  "label",
  "lat",
  "lon",
  "events",
  "on_time_share",
  "display",
  "sufficient",
  "route_id",
  "direction_id",
] as const;

export type MapStopRow = [
  string,
  string,
  number,
  number,
  number,
  number,
  string,
  boolean,
  string,
  number | null,
];
