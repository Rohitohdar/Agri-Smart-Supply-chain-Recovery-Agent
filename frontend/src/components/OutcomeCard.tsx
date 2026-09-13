import type { AgentRun } from "../api/types";
import { OUTCOME_META } from "../lib/describe";
import {
  compareToDeadline,
  formatCarbon,
  formatCost,
  formatDateTime,
  formatDecimal,
  formatHours,
  formatNumber,
} from "../lib/format";
import { numberAt, stringAt } from "../lib/read";
import { JsonDetails } from "./JsonDetails";
import { Stat } from "./Stat";
import { StatusPill } from "./StatusPill";

const REPLAN_CAP = 5;

/**
 * The run in one glance: what it cost, whether it lands in time, what it emitted,
 * how hard it had to think, and whether it succeeded.
 *
 * Only one figure here is the console's own arithmetic — the ETA-versus-deadline
 * comparison, which subtracts two timestamps the backend supplied. Everything
 * else is read straight out of the agent's response.
 */
export function OutcomeCard({ run }: { run: AgentRun | null }) {
  if (!run) {
    return (
      <section className="card" aria-labelledby="outcome-heading">
        <header className="card__header">
          <h2 id="outcome-heading">Outcome</h2>
          <StatusPill tone="neutral">No run yet</StatusPill>
        </header>
        <p className="muted">
          Cost, delivery time against the deadline, carbon, replans and the final verdict will
          appear here once the agent has run.
        </p>
      </section>
    );
  }

  const meta = OUTCOME_META[run.outcome];
  const option = run.plan?.options.at(0) ?? null;
  const action = run.actions.at(0) ?? null;
  const deadline = run.observed_demand.deadline;

  // Prefer the arrival the executed action actually created; fall back to nothing
  // rather than inventing an ETA from the estimate.
  const arrival = stringAt(action?.result, "shipment", "expected_arrival");
  const { verdict, marginHours } = compareToDeadline(arrival, deadline);

  const deliveryFits =
    option !== null && run.plan !== null
      ? option.total_delivery_hours <= run.plan.hours_available
      : null;

  return (
    <section className="card" aria-labelledby="outcome-heading">
      <header className="card__header">
        <h2 id="outcome-heading">Outcome</h2>
        <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
      </header>

      <p className={`notice notice--${meta.tone}`}>{meta.blurb}</p>

      {option ? (
        <>
          <h3>
            {action?.tool === "transfer_inventory" ? "Warehouse transfer" : "Vendor purchase"}
            {" — "}
            {option.label}
            <span className="muted"> · {formatNumber(option.quantity)} units</span>
          </h3>
          <div className="stats">
            <Stat label="Cost" value={formatCost(option.total_cost)} hint="as ranked by the optimizer" />
            <Stat
              label="Delivery"
              value={formatHours(option.total_delivery_hours)}
              hint={
                run.plan
                  ? `${formatHours(run.plan.hours_available)} available before the deadline`
                  : undefined
              }
              tone={deliveryFits === false ? "warn" : deliveryFits ? "ok" : "neutral"}
            />
            <Stat label="Carbon" value={formatCarbon(option.total_carbon)} hint="for this shipment" />
            <Stat
              label="Arrives"
              value={formatDateTime(arrival)}
              hint={
                verdict === "on_time" && marginHours !== null
                  ? `${formatHours(marginHours)} before the deadline`
                  : verdict === "late" && marginHours !== null
                    ? `${formatHours(Math.abs(marginHours))} after the deadline`
                    : "no arrival recorded"
              }
              tone={verdict === "on_time" ? "ok" : verdict === "late" ? "danger" : "neutral"}
            />
          </div>
        </>
      ) : (
        <h3>No action was taken</h3>
      )}

      <div className="stats stats--compact">
        <Stat
          label="Replans"
          value={formatNumber(run.replan_cycles)}
          hint={`cap ${REPLAN_CAP}`}
          tone={run.replan_cycles >= REPLAN_CAP ? "warn" : "neutral"}
        />
        <Stat label="Tool calls" value={formatNumber(run.tool_calls)} hint="this run" />
        <Stat
          label="Grounding"
          value={
            run.grounding
              ? run.grounding.fallback_used
                ? "Fallback"
                : run.grounding.regenerated
                  ? "Regenerated"
                  : "First pass"
              : "—"
          }
          hint={
            run.grounding?.fallback_reason
              ? run.grounding.fallback_reason
              : run.grounding && run.grounding.rejected_numbers.length > 0
                ? `${run.grounding.rejected_numbers.flat().join(", ")} rejected`
                : "every number traced to a tool result"
          }
          tone={
            run.grounding?.fallback_used ||
            (run.grounding && run.grounding.rejected_numbers.length > 0)
              ? "warn"
              : "ok"
          }
        />
        <Stat
          label="Verified"
          value={
            run.verify ? (run.verify.satisfied ? "Covered" : "Short") : "Not checked"
          }
          hint={
            run.verify
              ? `${formatNumber(run.verify.covered_quantity)} of ${formatNumber(
                  run.verify.required_quantity,
                )}`
              : "the run stopped before verification"
          }
          tone={run.verify?.satisfied ? "ok" : "warn"}
        />
      </div>

      <div className="block">
        <h3>The agent&apos;s own summary</h3>
        <blockquote className="quote">{run.explanation}</blockquote>
        {run.grounding ? (
          <JsonDetails
            label="view grounding and audit references"
            value={{
              grounding: run.grounding,
              audit_log_ids: run.audit_log_ids,
              run_id: run.run_id,
              outcome: run.outcome,
            }}
          />
        ) : null}
      </div>

      {action && !action.ok ? (
        <p className="notice notice--danger">
          The chosen action was refused by the backend: {action.error}
          {action.reason ? ` (${action.reason})` : ""}. The stock was not touched.
        </p>
      ) : null}

      {option ? (
        <JsonDetails
          label="view ranked options"
          value={run.plan}
          summary={`${formatNumber(run.plan?.options.length ?? 0)} feasible · ${formatNumber(
            run.plan?.excluded.length ?? 0,
          )} excluded`}
        />
      ) : null}

      <p className="card__note">
        Score {option ? formatDecimal(option.score, 2) : "—"} is the optimizer&apos;s weighted
        blend of normalized cost, delivery time and carbon — lower is better. The count of
        excluded candidates is{" "}
        {formatNumber(run.plan?.excluded.length ?? 0)}.
        {numberAt(action?.result, "vendor_available_before") !== null
          ? ` Vendor stock moved from ${formatNumber(
              numberAt(action?.result, "vendor_available_before"),
            )} to ${formatNumber(numberAt(action?.result, "vendor", "available_quantity"))}.`
          : ""}
      </p>
    </section>
  );
}
