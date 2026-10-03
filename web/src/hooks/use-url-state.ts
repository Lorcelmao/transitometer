"use client";

/**
 * Filter state kept in the URL query (?mode=bus&day=20260922), so every view has a shareable link.
 *
 * Reads window.location through useSyncExternalStore: the static HTML is rendered with the
 * defaults (server snapshot), and the browser then switches to the linked filters. Values not in
 * the allowed lists fall back to the defaults, so a hand-edited link cannot break a page.
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";

const EVENT = "transitometer:url-state";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

export function useUrlState<K extends string>(
  defaults: Record<K, string>,
  allowed: Partial<Record<K, readonly string[]>> = {},
): [Record<K, string>, (changes: Partial<Record<K, string>>) => void] {
  const search = useSyncExternalStore(
    subscribe,
    () => window.location.search,
    () => "",
  );
  const state = useMemo(() => {
    const params = new URLSearchParams(search);
    const result = { ...defaults };
    for (const key of Object.keys(defaults) as K[]) {
      const value = params.get(key);
      const options = allowed[key];
      if (value !== null && (!options || options.includes(value))) result[key] = value;
    }
    return result;
    // defaults and allowed are constant per page; the query string drives the state
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);
  const update = useCallback((changes: Partial<Record<K, string>>) => {
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(changes)) {
      if (typeof value === "string") params.set(key, value);
    }
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [state, update];
}
