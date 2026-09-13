/**
 * Which disruptions are still in force.
 *
 * There is no "list disruptions" endpoint, and inventing one client-side would
 * mean guessing a baseline (how would the console know the dealer's *original*
 * requirement?). So this reads the two things the backend does own:
 *
 * * the **audit trail** says which disruptions an operator injected, with the
 *   before/after values recorded at the time; and
 * * the **current snapshot** says whether each one is still in effect.
 *
 * A disruption is therefore "active" only when the state it changed is still
 * changed. Resetting the scenario, or cancelling/restoring the affected row,
 * makes the entry show as cleared rather than silently disappearing.
 */

import type {
  AuditEntry,
  Demand,
  DisruptionDetails,
  Route,
  Shipment,
  Vendor,
} from "../api/types";
import { formatHours, formatNumber } from "./format";
import { asRecord } from "./read";

export type DisruptionKind =
  | "shipment_delay"
  | "vendor_failure"
  | "route_block"
  | "demand_spike";

export interface ActiveDisruption {
  entryId: number;
  kind: DisruptionKind;
  /** ISO timestamp of the injection, straight from the audit entry. */
  at: string;
  title: string;
  /** What the live state says now, so "active" is checkable at a glance. */
  still: string;
  active: boolean;
}

export interface DisruptionContext {
  demand: Demand;
  shipments: Shipment[];
  routes: Route[];
  vendors: Vendor[];
}

/** Narrow an audit entry's `details` to the disruption union, when it is one. */
function asDisruption(details: Record<string, unknown>): DisruptionDetails | null {
  const kind = details.disruption;
  if (
    kind === "shipment_delay" ||
    kind === "vendor_failure" ||
    kind === "route_block" ||
    kind === "demand_spike"
  ) {
    return details as unknown as DisruptionDetails;
  }
  return null;
}

/**
 * The newest entry per affected row wins: delaying the same shipment twice
 * should read as one disruption, not two.
 */
export function deriveDisruptions(
  entries: AuditEntry[],
  context: DisruptionContext,
): ActiveDisruption[] {
  const seen = new Set<string>();
  const result: ActiveDisruption[] = [];

  // Newest first, so the first entry per target is the current one.
  const ordered = [...entries].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );

  for (const entry of ordered) {
    const details = asDisruption(entry.details);
    if (!details) continue;

    const key =
      details.disruption === "shipment_delay"
        ? `shipment:${details.shipment_id}`
        : details.disruption === "vendor_failure"
          ? `vendor:${details.vendor_id}`
          : details.disruption === "route_block"
            ? `route:${details.route_id}`
            : `dealer:${details.dealer_id}`;
    if (seen.has(key)) continue;
    seen.add(key);

    if (details.disruption === "shipment_delay") {
      const shipment = context.shipments.find((item) => item.id === details.shipment_id);
      const active = shipment?.status === "DELAYED";
      result.push({
        entryId: entry.id,
        kind: details.disruption,
        at: entry.timestamp,
        title: `Shipment #${details.shipment_id} delayed by ${formatHours(details.total_delay_hours)}`,
        still: shipment
          ? `Shipment #${shipment.id} is currently ${shipment.status}`
          : "That shipment no longer exists",
        active,
      });
      continue;
    }

    if (details.disruption === "vendor_failure") {
      const vendor = context.vendors.find((item) => item.id === details.vendor_id);
      const active = vendor ? !vendor.is_available : false;
      result.push({
        entryId: entry.id,
        kind: details.disruption,
        at: entry.timestamp,
        title: `Vendor barred: ${details.vendor_name ?? `#${details.vendor_id}`}`,
        still: vendor
          ? `${vendor.name} is ${vendor.is_available ? "available again" : "still unavailable"}`
          : "That vendor no longer exists",
        active,
      });
      continue;
    }

    if (details.disruption === "route_block") {
      const route = context.routes.find((item) => item.id === details.route_id);
      const active = route ? !route.is_available : false;
      result.push({
        entryId: entry.id,
        kind: details.disruption,
        at: entry.timestamp,
        title: `Route blocked: ${details.from_location_id} → ${details.to_location_id}`,
        still: route
          ? `Route #${route.id} is ${route.is_available ? "open again" : "still closed"}`
          : "That route no longer exists",
        active,
      });
      continue;
    }

    const active =
      context.demand.required_quantity === details.required_quantity.after;
    result.push({
      entryId: entry.id,
      kind: details.disruption,
      at: entry.timestamp,
      title: `Demand raised ${formatNumber(details.required_quantity.before)} → ${formatNumber(
        details.required_quantity.after,
      )} units`,
      still: active
        ? `The requirement is still ${formatNumber(context.demand.required_quantity)} units`
        : `The requirement is back to ${formatNumber(context.demand.required_quantity)} units`,
      active,
    });
  }

  // Active first, then newest.
  return result.sort((a, b) => Number(b.active) - Number(a.active));
}

/** Count of the disruptions still in force. */
export function countActive(disruptions: ActiveDisruption[]): number {
  return disruptions.filter((item) => item.active).length;
}

/** Read `disruption_injected` entries out of a raw audit payload. */
export function disruptionEntries(entries: AuditEntry[]): AuditEntry[] {
  return entries.filter((entry) => {
    if (entry.action_type !== "disruption_injected") return false;
    return asRecord(entry.details) !== null && asDisruption(entry.details) !== null;
  });
}
