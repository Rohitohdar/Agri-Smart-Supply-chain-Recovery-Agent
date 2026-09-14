import { useState } from "react";

import type { Snapshot } from "../api/hooks";
import type { ShipmentStatus } from "../api/types";
import { isShipmentActive, shipmentLabel, shipmentTone, type Tone } from "../lib/describe";
import { formatDateTime, formatHours, formatNumber, formatRelative } from "../lib/format";
import { inboundByDeadline, locationName } from "../lib/supply";
import type { ActiveDisruption } from "../lib/disruptions";
import { Meter, Stat } from "./Stat";
import { StatusPill } from "./StatusPill";

const STATUS_ORDER: ShipmentStatus[] = [
  "PENDING",
  "IN_TRANSIT",
  "DELAYED",
  "ARRIVED",
  "CANCELLED",
];

const nameOfRoute = (snapshot: Snapshot, locationId: number): string =>
  locationName(
    {
      warehouses: snapshot.inventory.warehouses,
      dealers: snapshot.inventory.dealers,
      vendors: snapshot.vendors,
    },
    locationId,
  );

function CollapsibleBlock({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="block">
      <button
        type="button"
        className="collapsible__toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <h3 style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {title}
          {badge}
        </h3>
        <span
          className={`collapsible__chevron${open ? " collapsible__chevron--open" : ""}`}
          aria-hidden="true"
        >
          ▼
        </span>
      </button>
      {open ? <div style={{ marginTop: 8 }}>{children}</div> : null}
    </div>
  );
}

export function SystemStatusPanel({
  snapshot,
  disruptions,
  disruptionsLoading,
}: {
  snapshot: Snapshot | null;
  disruptions: ActiveDisruption[];
  disruptionsLoading: boolean;
}) {
  if (!snapshot) {
    return (
      <section className="card" aria-labelledby="status-heading">
        <header className="card__header">
          <h2 id="status-heading">System status</h2>
          <StatusPill tone="neutral">Waiting for the backend…</StatusPill>
        </header>
      </section>
    );
  }

  const { demand, shipments, routes, vendors } = snapshot;
  const activeDisruptions = disruptions.filter((item) => item.active);
  const violated = demand.constraint_violated;

  const statusTone: Tone = violated ? "danger" : activeDisruptions.length > 0 ? "warn" : "ok";

  const { onTime: inboundOnTime, late: inboundLate } = inboundByDeadline(demand);
  const totalCoverage = demand.available_quantity + inboundOnTime;
  const isCovered = totalCoverage >= demand.required_quantity;

  // Plain-language lead sentence
  const leadText = violated
    ? `Short by ${formatNumber(demand.on_hand_shortfall)} units — the agent needs to act.`
    : isCovered
      ? `You have enough supply arriving on time — no action needed.`
      : `Coverage is marginal — monitor closely.`;

  const blockedRoutes = routes.filter((route) => !route.is_available);
  const downVendors = vendors.filter((vendor) => !vendor.is_available);
  const byStatus = STATUS_ORDER.map((status) => ({
    status,
    count: shipments.filter((shipment) => shipment.status === status).length,
  })).filter((row) => row.count > 0);

  return (
    <section className="card card--wide" aria-labelledby="status-heading">
      <header className="card__header">
        <h2 id="status-heading">System status</h2>
        <div className="card__header-meta">
          <span className="muted">as of {formatRelative(snapshot.fetchedAt)}</span>
          <StatusPill tone={statusTone}>
            {violated ? "Constraint violated" : activeDisruptions.length > 0 ? "Degraded" : "Healthy"}
          </StatusPill>
        </div>
      </header>

      {/* Plain-language lead */}
      <p className={`lead lead--${statusTone}`}>{leadText}</p>

      <div className="stats">
        <Stat
          label="Dealer needs"
          value={formatNumber(demand.required_quantity)}
          hint={`by ${formatDateTime(demand.deadline)}`}
        />
        <Stat
          label="On hand"
          value={formatNumber(demand.available_quantity)}
          hint={demand.dealer_name}
          tone={demand.available_quantity >= demand.required_quantity ? "ok" : "neutral"}
        />
        <Stat
          label="On-hand shortfall"
          value={formatNumber(demand.on_hand_shortfall)}
          hint={
            demand.on_hand_shortfall > 0
              ? "covered by on-time inbound supply"
              : "requirement met on hand"
          }
          tone={demand.on_hand_shortfall > 0 ? "neutral" : "ok"}
        />
        <Stat
          label="Inbound by deadline"
          value={formatNumber(inboundOnTime)}
          hint={
            inboundLate > 0
              ? `${formatNumber(inboundLate)} units arrive too late`
              : `${formatNumber(demand.active_shipments.length)} active shipment(s)`
          }
          tone={inboundLate > 0 ? "warn" : "info"}
        />
      </div>

      <div className="block">
        <h3>Requirement coverage</h3>
        <Meter
          value={demand.available_quantity}
          max={demand.required_quantity}
          tone={violated ? "danger" : "ok"}
          caption={
            <>
              On hand {formatNumber(demand.available_quantity)} / {formatNumber(demand.required_quantity)}
              {inboundOnTime > 0
                ? ` · plus ${formatNumber(inboundOnTime)} arriving in time`
                : ""}
            </>
          }
        />
        {violated && demand.constraint_violations.length > 0 ? (
          <ul className="violations">
            {demand.constraint_violations.map((violation) => (
              <li key={violation}>{violation}</li>
            ))}
          </ul>
        ) : (
          <p className="notice notice--ok">No constraint is currently violated.</p>
        )}
      </div>

      <div className="block">
        <h3>
          Active disruptions
          {activeDisruptions.length > 0 ? (
            <span className="badge badge--danger" style={{ marginLeft: 6 }}>{activeDisruptions.length}</span>
          ) : null}
        </h3>
        {disruptionsLoading ? (
          <p className="muted">Reading the audit trail…</p>
        ) : disruptions.length === 0 ? (
          <p className="notice notice--ok">
            None injected. Use the disruption panel to break the scenario.
          </p>
        ) : (
          <ul className="disruption-list">
            {disruptions.map((item) => (
              <li key={item.entryId} className={item.active ? "disruption is-active" : "disruption"}>
                <StatusPill tone={item.active ? "danger" : "neutral"}>
                  {item.active ? "Active" : "Cleared"}
                </StatusPill>
                <div className="disruption__body">
                  <div className="disruption__title">{item.title}</div>
                  <div className="disruption__meta">
                    {item.still} · injected {formatRelative(item.at)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Shipments — always visible summary, detail behind toggle */}
      <CollapsibleBlock
        title="Shipments"
        defaultOpen={shipments.some((s) => s.status === "DELAYED")}
        badge={
          <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {byStatus.map((row) => (
              <StatusPill key={row.status} tone={shipmentTone(row.status)}>
                {shipmentLabel(row.status)} · {row.count}
              </StatusPill>
            ))}
            {shipments.length === 0 ? <span className="muted">No shipments.</span> : null}
          </span>
        }
      >
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Route</th>
              <th className="num">Units</th>
              <th>Status</th>
              <th>Expected</th>
            </tr>
          </thead>
          <tbody>
            {shipments.map((shipment) => (
              <tr key={shipment.id} className={isShipmentActive(shipment.status) ? undefined : "row--muted"}>
                <td>{shipment.id}</td>
                <td>
                  {nameOfRoute(snapshot, shipment.from_id)} → {nameOfRoute(snapshot, shipment.to_id)}
                </td>
                <td className="num">{formatNumber(shipment.quantity)}</td>
                <td>
                  <StatusPill tone={shipmentTone(shipment.status)}>
                    {shipmentLabel(shipment.status)}
                  </StatusPill>
                </td>
                <td>
                  {formatDateTime(shipment.expected_arrival)}
                  {shipment.delay_hours > 0 ? (
                    <span className="muted"> · +{formatHours(shipment.delay_hours)}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CollapsibleBlock>

      <div className="split">
        {/* Routes — collapsed by default unless something is blocked */}
        <CollapsibleBlock
          title="Routes"
          defaultOpen={blockedRoutes.length > 0}
          badge={
            <span className="muted" style={{ fontWeight: 400, fontSize: "0.82rem", textTransform: "none", letterSpacing: 0 }}>
              {formatNumber(routes.length - blockedRoutes.length)} of {formatNumber(routes.length)} open
              {blockedRoutes.length > 0 ? (
                <StatusPill tone="danger" > · {blockedRoutes.length} blocked</StatusPill>
              ) : null}
            </span>
          }
        >
          <ul className="mini-list">
            {routes.map((route) => (
              <li key={route.id}>
                <StatusPill tone={route.is_available ? "ok" : "danger"}>
                  {route.is_available ? "Open" : "Blocked"}
                </StatusPill>
                <span>
                  #{route.id} {nameOfRoute(snapshot, route.from_location_id)} →{" "}
                  {nameOfRoute(snapshot, route.to_location_id)}
                </span>
                <span className="muted">
                  {formatHours(route.travel_time_hours)} · {formatNumber(route.distance_km)} km
                </span>
              </li>
            ))}
          </ul>
        </CollapsibleBlock>

        {/* Vendors — collapsed by default unless something is down */}
        <CollapsibleBlock
          title="Vendors"
          defaultOpen={downVendors.length > 0}
          badge={
            <span className="muted" style={{ fontWeight: 400, fontSize: "0.82rem", textTransform: "none", letterSpacing: 0 }}>
              {formatNumber(vendors.length - downVendors.length)} of {formatNumber(vendors.length)} available
              {downVendors.length > 0 ? (
                <StatusPill tone="danger"> · {downVendors.length} down</StatusPill>
              ) : null}
            </span>
          }
        >
          <ul className="mini-list">
            {vendors.map((vendor) => (
              <li key={vendor.id}>
                <StatusPill tone={vendor.is_available ? "ok" : "danger"}>
                  {vendor.is_available ? "Available" : "Unavailable"}
                </StatusPill>
                <span>{vendor.name}</span>
                <span className="muted">
                  {formatNumber(vendor.available_quantity)} {vendor.unit} · {formatHours(vendor.delivery_hours)}
                </span>
              </li>
            ))}
          </ul>
        </CollapsibleBlock>
      </div>
    </section>
  );
}
