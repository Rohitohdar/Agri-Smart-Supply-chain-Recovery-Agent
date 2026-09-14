import { useEffect, useState, type ReactNode } from "react";

import type { Snapshot } from "../api/hooks";
import type { WouldChooseResponse } from "../api/types";
import {
  errorMessage,
  getWouldChoose,
  isMissingApiKey,
  isRateLimited,
  isUnauthorized,
  simulateDemandSpike,
  simulateRouteBlock,
  simulateShipmentDelay,
  simulateVendorFailure,
} from "../api/client";
import { formatHours, formatNumber } from "../lib/format";
import { isShipmentActive } from "../lib/describe";
import { locationName } from "../lib/supply";
import { StatusPill } from "./StatusPill";

type ControlKey = "delay" | "route" | "vendor" | "spike";

/** How long a success or refusal message stays on screen. */
const MESSAGE_TTL_MS = 9_000;

interface Outcome {
  key: ControlKey;
  text: string;
}

/**
 * One disruption trigger.
 *
 * The four triggers share this shell — heading, inputs, and a button that owns
 * its own busy and disabled state — and differ only in their fields and in what
 * they call, so each reads as a declaration rather than a repeated block.
 */
function Control({
  title,
  hint,
  action,
  busyLabel,
  busy,
  locked,
  onAction,
  hintText,
  children,
}: {
  title: string;
  hint: string;
  action: string;
  busyLabel: string;
  busy: boolean;
  locked: boolean;
  onAction: () => void;
  hintText?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="control">
      <div className="control__head">
        <h3>{title}</h3>
        <span className="muted">{hint}</span>
      </div>
      <div className="control__row">
        {children}
        <button
          type="button"
          className="button button--danger"
          disabled={locked || busy}
          onClick={onAction}
        >
          {busy ? busyLabel : action}
        </button>
      </div>
      {hintText ? <p className="control__hint">{hintText}</p> : null}
    </div>
  );
}

export function DisruptionPanel({
  snapshot,
  blockedReason,
  onChanged,
}: {
  snapshot: Snapshot | null;
  /** Set when the console cannot authenticate a write; disables every control. */
  blockedReason: string | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<ControlKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [confirmSpike, setConfirmSpike] = useState(false);

  const [precheck, setPrecheck] = useState<WouldChooseResponse | null>(null);
  const [precheckBusy, setPrecheckBusy] = useState(false);
  const [precheckError, setPrecheckError] = useState<string | null>(null);

  async function runPrecheck() {
    setPrecheckBusy(true);
    setPrecheckError(null);
    setPrecheck(null);
    try {
      setPrecheck(await getWouldChoose());
    } catch (caught) {
      setPrecheckError(errorMessage(caught));
    } finally {
      setPrecheckBusy(false);
    }
  }

  const [shipmentId, setShipmentId] = useState<number | null>(null);
  const [delayHours, setDelayHours] = useState("12");
  const [routeId, setRouteId] = useState<number | null>(null);
  const [vendorId, setVendorId] = useState<number | null>(null);
  const [spikeValue, setSpikeValue] = useState<string | null>(null);

  const activeShipments = snapshot?.shipments.filter((s) => isShipmentActive(s.status)) ?? [];
  const openRoutes = snapshot?.routes.filter((route) => route.is_available) ?? [];
  const upVendors = snapshot?.vendors.filter((vendor) => vendor.is_available) ?? [];
  const demand = snapshot?.demand ?? null;

  const lookups = snapshot
    ? {
        warehouses: snapshot.inventory.warehouses,
        dealers: snapshot.inventory.dealers,
        vendors: snapshot.vendors,
      }
    : null;
  const nameOf = (locationId: number) =>
    lookups ? locationName(lookups, locationId) : `location #${locationId}`;

  // Keep each selection valid as the live data changes (a reset, an action).
  useEffect(() => {
    if (shipmentId === null || !activeShipments.some((s) => s.id === shipmentId)) {
      setShipmentId(activeShipments[0]?.id ?? null);
    }
  }, [activeShipments, shipmentId]);

  useEffect(() => {
    if (routeId === null || !openRoutes.some((route) => route.id === routeId)) {
      setRouteId(openRoutes[0]?.id ?? null);
    }
  }, [openRoutes, routeId]);

  useEffect(() => {
    if (vendorId === null || !upVendors.some((vendor) => vendor.id === vendorId)) {
      setVendorId(upVendors[0]?.id ?? null);
    }
  }, [upVendors, vendorId]);

  // Reset spike confirm when the outcome/error clears
  useEffect(() => {
    if (outcome === null && error === null) return;
    setConfirmSpike(false);
    const timer = window.setTimeout(() => {
      setOutcome(null);
      setError(null);
    }, MESSAGE_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [outcome, error]);

  /** A spike must exceed the live requirement, so suggest 50% above it. */
  const suggestedSpike = demand ? Math.ceil(demand.required_quantity * 1.5) : null;
  const spikeText = spikeValue ?? (suggestedSpike === null ? "" : String(suggestedSpike));
  const spikeNumber = Number(spikeText);
  const spikeValid =
    demand !== null &&
    Number.isInteger(spikeNumber) &&
    spikeNumber > demand.required_quantity;

  const delayNumber = Number(delayHours);
  const delayValid = Number.isFinite(delayNumber) && delayNumber > 0;

  function describeFailure(caught: unknown): string {
    if (isMissingApiKey(caught)) {
      return "Enter the API key in the Connection panel first.";
    }
    if (isUnauthorized(caught)) {
      return "The backend rejected the API key. Check it in the Connection panel.";
    }
    if (isRateLimited(caught)) {
      return errorMessage(caught);
    }
    return errorMessage(caught);
  }

  async function run(key: ControlKey, task: () => Promise<string>) {
    setBusy(key);
    setError(null);
    setOutcome(null);
    try {
      const text = await task();
      setOutcome({ key, text });
      onChanged();
    } catch (caught) {
      setError(describeFailure(caught));
    } finally {
      setBusy(null);
    }
  }

  const locked = blockedReason !== null;
  const anyBusy = busy !== null;

  const target = precheck?.disruption_target ?? null;
  const topOption = precheck?.top_option ?? null;

  function targetSummary(): string | null {
    if (!target) return null;
    if (target.kind === "vendor_failure") return `Disable vendor "${target.vendor_name}" (id ${target.vendor_id})`;
    if (target.kind === "route_block") return `Block route #${target.route_id}`;
    if (target.kind === "shipment_delay") return `Delay shipment #${target.shipment_id} by 72 h`;
    return null;
  }

  return (
    <section className="card" aria-labelledby="disruption-heading">
      <header className="card__header">
        <h2 id="disruption-heading">Disruption control panel</h2>
        <StatusPill tone={locked ? "warn" : "ok"}>{locked ? "Locked" : "Ready"}</StatusPill>
      </header>

      <p className="muted">
        Each button injects one disruption through the backend&apos;s <code>/simulate/*</code>{" "}
        endpoints. Every call is validated against live state, written to the audit trail, and
        can be refused — you will be told, not faked.
      </p>

      {/* Demo pre-check */}
      <div className="control">
        <div className="control__head">
          <h3>Demo pre-check</h3>
          <span className="muted">Run before recording — picks the targeted disruption for you</span>
        </div>
        <div className="control__row">
          <button
            type="button"
            className="button"
            disabled={precheckBusy}
            onClick={() => void runPrecheck()}
          >
            {precheckBusy ? "Checking…" : "What would the agent choose?"}
          </button>
        </div>
        {precheckError ? <p className="notice notice--danger">{precheckError}</p> : null}
        {precheck && topOption ? (
          <div className="notice notice--info" style={{ marginTop: "0.5rem" }}>
            <strong>Agent would pick:</strong>{" "}
            {topOption.action} — {topOption.label} × {topOption.quantity} (score {topOption.score.toFixed(4)})
            {target ? (
              <>
                <br />
                <strong>Apply this disruption first:</strong> {targetSummary()}
                <br />
                <span className="muted" style={{ fontSize: "0.8em" }}>{precheck.demo_instruction}</span>
              </>
            ) : null}
          </div>
        ) : precheck && !topOption ? (
          <p className="notice notice--warn">No feasible option — reset the scenario before recording.</p>
        ) : null}
      </div>

      {blockedReason ? <p className="notice notice--warn">{blockedReason}</p> : null}
      {error ? <p className="notice notice--danger">{error}</p> : null}
      {outcome ? <p className="notice notice--ok">{outcome.text}</p> : null}

      <div className="controls">
        <Control
          title="Delay a shipment"
          hint="Marks it DELAYED and pushes the ETA"
          action="Delay shipment"
          busyLabel="Delaying…"
          busy={busy === "delay"}
          locked={locked || anyBusy || shipmentId === null || !delayValid}
          onAction={() =>
            void run("delay", async () => {
              const result = await simulateShipmentDelay(shipmentId ?? 0, delayNumber);
              return `Shipment #${result.shipment.id} is now ${result.shipment.status}, arriving ${formatHours(
                result.delay_hours,
              )} later.`;
            })
          }
        >
          <label>
            <span>Shipment</span>
            <select
              value={shipmentId ?? ""}
              disabled={locked || activeShipments.length === 0}
              onChange={(event) => setShipmentId(Number(event.target.value))}
            >
              {activeShipments.length === 0 ? <option value="">none active</option> : null}
              {activeShipments.map((shipment) => (
                <option key={shipment.id} value={shipment.id}>
                  #{shipment.id} · {formatNumber(shipment.quantity)} units · {shipment.status}
                </option>
              ))}
            </select>
          </label>
          <label className="control__narrow">
            <span>Hours</span>
            <input
              type="number"
              min={0.5}
              step={0.5}
              value={delayHours}
              disabled={locked}
              onChange={(event) => setDelayHours(event.target.value)}
            />
          </label>
        </Control>

        <Control
          title="Block a route"
          hint="Takes it out of service for reroutes"
          action="Block route"
          busyLabel="Blocking…"
          busy={busy === "route"}
          locked={locked || anyBusy || routeId === null}
          onAction={() =>
            void run("route", async () => {
              const result = await simulateRouteBlock(routeId ?? 0);
              return `Route #${result.route.id} is now blocked.`;
            })
          }
        >
          <label>
            <span>Route</span>
            <select
              value={routeId ?? ""}
              disabled={locked || openRoutes.length === 0}
              onChange={(event) => setRouteId(Number(event.target.value))}
            >
              {openRoutes.length === 0 ? <option value="">none open</option> : null}
              {openRoutes.map((route) => (
                <option key={route.id} value={route.id}>
                  #{route.id} · {nameOf(route.from_location_id)} → {nameOf(route.to_location_id)} ·{" "}
                  {formatHours(route.travel_time_hours)}
                </option>
              ))}
            </select>
          </label>
        </Control>

        <Control
          title="Disable a vendor"
          hint="Removes it from the options the agent can pick"
          action="Disable vendor"
          busyLabel="Disabling…"
          busy={busy === "vendor"}
          locked={locked || anyBusy || vendorId === null}
          onAction={() =>
            void run("vendor", async () => {
              const result = await simulateVendorFailure(vendorId ?? 0);
              return `${result.vendor.name} is now unavailable.`;
            })
          }
        >
          <label>
            <span>Vendor</span>
            <select
              value={vendorId ?? ""}
              disabled={locked || upVendors.length === 0}
              onChange={(event) => setVendorId(Number(event.target.value))}
            >
              {upVendors.length === 0 ? <option value="">none available</option> : null}
              {upVendors.map((vendor) => (
                <option key={vendor.id} value={vendor.id}>
                  {vendor.name} · {formatNumber(vendor.available_quantity)} {vendor.unit} ·{" "}
                  {formatHours(vendor.delivery_hours)}
                </option>
              ))}
            </select>
          </label>
        </Control>

        <Control
          title="Raise demand"
          hint="Must exceed the current requirement"
          action="Raise demand"
          busyLabel="Raising…"
          busy={busy === "spike"}
          locked={locked || anyBusy || !spikeValid || demand === null}
          onAction={() => {
            if (!confirmSpike) { setConfirmSpike(true); return; }
            setConfirmSpike(false);
            void run("spike", async () => {
              const result = await simulateDemandSpike(demand?.dealer_id ?? 0, spikeNumber);
              return `Requirement raised ${formatNumber(
                result.previous_required_quantity,
              )} → ${formatNumber(result.dealer.required_quantity)}; shortfall went ${formatNumber(
                result.shortage_before,
              )} → ${formatNumber(result.shortage_after)}.`;
            });
          }}
          hintText={
            <>
              {demand
                ? `Current requirement: ${formatNumber(demand.required_quantity)} units.`
                : "Waiting for demand…"}
              {spikeText && !spikeValid && demand
                ? ` Must be greater than ${formatNumber(demand.required_quantity)}.`
                : ""}
            </>
          }
        >
          {/* Inline confirm for demand spike */}
          {confirmSpike ? (
            <div className="inline-confirm">
              <span className="inline-confirm__prompt">⚠ Raise to {formatNumber(spikeNumber)} units?</span>
              <button
                type="button"
                className="button button--danger"
                onClick={() => {
                  setConfirmSpike(false);
                  void run("spike", async () => {
                    const result = await simulateDemandSpike(demand?.dealer_id ?? 0, spikeNumber);
                    return `Requirement raised ${formatNumber(
                      result.previous_required_quantity,
                    )} → ${formatNumber(result.dealer.required_quantity)}; shortfall went ${formatNumber(
                      result.shortage_before,
                    )} → ${formatNumber(result.shortage_after)}.`;
                  });
                }}
              >
                Confirm
              </button>
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setConfirmSpike(false)}
              >
                Cancel
              </button>
            </div>
          ) : null}
          <label className="control__narrow">
            <span>New requirement</span>
            <input
              type="number"
              min={1}
              step={1}
              value={spikeText}
              disabled={locked || demand === null}
              onChange={(event) => setSpikeValue(event.target.value)}
            />
          </label>
        </Control>
      </div>

      <p className="card__note">
        The reset control is in the Connection panel — each injected disruption is cumulative, so
        restore the scenario between run-throughs.
      </p>
    </section>
  );
}
