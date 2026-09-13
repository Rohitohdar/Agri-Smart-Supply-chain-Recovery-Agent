/**
 * Polling hooks.
 *
 * Polling (not websockets) is deliberate: the backend exposes no streaming
 * endpoint, so a socket would mean changing it. To stay a well-behaved client
 * each tick is scheduled *after* the previous one completes rather than on a
 * fixed timer, so requests can never pile up, and polling pauses while the tab
 * is hidden. At the default 4s interval the console issues ~75 requests a
 * minute, comfortably inside the backend's default `RATE_LIMIT_DEFAULT` of
 * 200/minute.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getDemand,
  getHealth,
  getInventory,
  getRoutes,
  getShipments,
  getVendors,
} from "./client";
import type {
  Demand,
  HealthResponse,
  InventoryOverview,
  Route,
  Shipment,
  Vendor,
} from "./types";

export interface Polled<T> {
  data: T | null;
  error: unknown;
  refreshing: boolean;
  lastUpdatedAt: Date | null;
  refresh: () => void;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  enabled = true,
): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [nonce, setNonce] = useState(0);

  // Keep the latest fetcher without making callers memoise it.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: number | undefined;
    const controller = new AbortController();

    const schedule = () => {
      if (!cancelled) timer = window.setTimeout(tick, intervalMs);
    };

    const tick = async () => {
      // A hidden tab should not spend the operator's rate-limit budget.
      if (document.visibilityState === "hidden") {
        schedule();
        return;
      }
      setRefreshing(true);
      try {
        const next = await fetcherRef.current(controller.signal);
        if (cancelled) return;
        setData(next);
        setError(null);
        setLastUpdatedAt(new Date());
      } catch (caught) {
        if (!cancelled && !isAbort(caught)) setError(caught);
      } finally {
        if (!cancelled) setRefreshing(false);
        schedule();
      }
    };

    const onVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVisible);

    void tick();
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [enabled, intervalMs, nonce, refresh]);

  return { data, error, refreshing, lastUpdatedAt, refresh };
}

/** Everything the status panels read, refreshed as one consistent set. */
export interface Snapshot {
  demand: Demand;
  shipments: Shipment[];
  routes: Route[];
  vendors: Vendor[];
  inventory: InventoryOverview;
  fetchedAt: string;
}

export function useSnapshot(intervalMs: number): Polled<Snapshot> {
  const fetcher = useCallback(async (signal: AbortSignal): Promise<Snapshot> => {
    const [demand, shipments, routes, vendors, inventory] = await Promise.all([
      getDemand(signal),
      getShipments(signal),
      getRoutes(signal),
      getVendors(signal),
      getInventory(signal),
    ]);
    return { demand, shipments, routes, vendors, inventory, fetchedAt: new Date().toISOString() };
  }, []);

  return usePolling(fetcher, intervalMs);
}

/** Connection health, polled slowly — it only changes when the backend restarts. */
export function useHealth(intervalMs = 10_000): Polled<HealthResponse> {
  const fetcher = useCallback((signal: AbortSignal) => getHealth(signal), []);
  return usePolling(fetcher, intervalMs);
}

// --- persisted operator settings -------------------------------------------

export function useLocalStorage<T>(
  key: string,
  initial: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? initial : (JSON.parse(stored) as T);
    } catch {
      return initial;
    }
  });

  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        if (next === "" || next === null) window.localStorage.removeItem(key);
        else window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Storage disabled (private mode): the session still works, just not persisted.
      }
    },
    [key],
  );

  return [value, update];
}
