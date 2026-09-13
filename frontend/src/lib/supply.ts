/**
 * Derived supply figures, in one place.
 *
 * The only arithmetic the console does is *adding up numbers the backend already
 * sent* — never estimating one. `verify_state` uses the same rule (stock on hand
 * plus inbound arriving by the deadline), so the panel and the agent's own
 * verdict agree by construction.
 */

import type { DealerStock, Demand, Vendor, WarehouseStock } from "../api/types";
import { parseUtc } from "./format";

/** The slices of a snapshot needed to resolve a location id to a name. */
export interface LocationLookups {
  warehouses: WarehouseStock[];
  dealers: DealerStock[];
  vendors: Vendor[];
}

/**
 * A location id as a readable name.
 *
 * Suppliers participate in shipping without holding inventory, so they are
 * absent from `/inventory` — but they *are* the vendors, and showing "2" while
 * the same console lists "GreenFields Fertilizers" would be needlessly cryptic.
 */
export function locationName(lookups: LocationLookups, locationId: number): string {
  const warehouse = lookups.warehouses.find((item) => item.location_id === locationId);
  if (warehouse) return warehouse.name;
  const dealer = lookups.dealers.find((item) => item.location_id === locationId);
  if (dealer) return dealer.name;
  const vendor = lookups.vendors.find((item) => item.id === locationId);
  if (vendor) return vendor.name;
  return `location #${locationId}`;
}

export interface InboundSplit {
  /** Units from active shipments whose expected arrival is at or before the deadline. */
  onTime: number;
  /** Units arriving after it, or with no expected arrival recorded. */
  late: number;
}

export function inboundByDeadline(demand: Demand): InboundSplit {
  const deadline = parseUtc(demand.deadline);
  let onTime = 0;
  let late = 0;
  for (const shipment of demand.active_shipments) {
    const arrival = parseUtc(shipment.expected_arrival);
    if (arrival && deadline && arrival.getTime() <= deadline.getTime()) {
      onTime += shipment.quantity;
    } else {
      late += shipment.quantity;
    }
  }
  return { onTime, late };
}

/** Stock on hand plus the inbound quantity that lands in time. */
export function coverage(demand: Demand): number {
  return demand.available_quantity + inboundByDeadline(demand).onTime;
}
