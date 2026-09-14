import type { AgentRun, ExcludedOption, RankedOption } from "../api/types";
import { OUTCOME_META } from "../lib/describe";
import { downloadAuditReport } from "../lib/export";
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

/** Margin threshold below which we surface a low-margin risk flag (10% of hours available). */
const THIN_MARGIN_RATIO = 0.1;

const EXCLUSION_REASON_LABEL: Record<string, string> = {
  no_available_route: "No route",
  insufficient_quantity: "Not enough stock",
  misses_deadline: "Misses deadline",
};

function reasonLabel(reason: string): string {
  return EXCLUSION_REASON_LABEL[reason] ?? reason.replace(/_/g, " ");
}

// --- A: Candidate explainability table -------------------------------------

function CandidateTable({ options, excluded, selectedReferenceId }: {
  options: RankedOption[];
  excluded: ExcludedOption[];
  selectedReferenceId: number | null;
}) {
  return (
    <div className="block">
      <h3>All candidates the optimizer considered</h3>
      <div style={{ overflowX: "auto" }}>
        <table className="candidate-table" aria-label="Recovery candidates ranked by the optimizer">
          <thead>
            <tr>
              <th>Option</th>
              <th>Action</th>
              <th className="num">Cost</th>
              <th className="num">Delivery</th>
              <th className="num">Carbon</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {options.map((opt) => (
              <tr
                key={`opt-${opt.reference_id}-${opt.action}`}
                className={opt.reference_id === selectedReferenceId ? "row--selected" : undefined}
              >
                <td>
                  <strong>{opt.label}</strong>
                  {opt.reference_id === selectedReferenceId ? (
                    <span style={{ marginLeft: 6 }}>
                      <StatusPill tone="ok">Selected</StatusPill>
                    </span>
                  ) : null}
                </td>
                <td>{opt.action.replace(/_/g, " ")}</td>
                <td className="num">{formatCost(opt.total_cost)}</td>
                <td className="num">{formatHours(opt.total_delivery_hours)}</td>
                <td className="num">{formatCarbon(opt.total_carbon)}</td>
                <td>
                  {opt.single_feasible_option ? (
                    <StatusPill tone="warn">Only option</StatusPill>
                  ) : (
                    <StatusPill tone="ok">Rank {opt.rank} · score {opt.score.toFixed(3)}</StatusPill>
                  )}
                </td>
              </tr>
            ))}
            {excluded.map((ex) => (
              <tr
                key={`ex-${ex.reference_id}-${ex.action}`}
                className="row--excluded"
              >
                <td>{ex.label}</td>
                <td>{ex.action.replace(/_/g, " ")}</td>
                <td className="num">—</td>
                <td className="num">
                  {ex.delivery_hours !== null ? formatHours(ex.delivery_hours) : "—"}
                </td>
                <td className="num">—</td>
                <td>
                  <span className="reason-tag">
                    ✗ {reasonLabel(ex.reason)}
                    {ex.reason === "misses_deadline" && ex.delivery_hours !== null && ex.hours_available !== null
                      ? ` (${formatHours(ex.delivery_hours)} vs ${formatHours(ex.hours_available)} available)`
                      : ""}
                    {ex.reason === "insufficient_quantity"
                      ? ` (${formatNumber(ex.available_quantity)} available)`
                      : ""}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="card__note">
        Green rows are feasible options ranked by a weighted score (40% cost · 40% delivery · 20% carbon).
        Greyed rows were ruled out before scoring — the reason column shows exactly why.
      </p>
    </div>
  );
}

// --- G: Risk flag ----------------------------------------------------------

function RiskFlag({ option, hoursAvailable, feasibleCount }: {
  option: RankedOption;
  hoursAvailable: number;
  feasibleCount: number;
}) {
  const thinMargin =
    hoursAvailable > 0 &&
    (hoursAvailable - option.total_delivery_hours) / hoursAvailable < THIN_MARGIN_RATIO;

  const noBackup = feasibleCount <= 1;

  if (!thinMargin && !noBackup) return null;

  const reasons: string[] = [];
  if (thinMargin) {
    const margin = hoursAvailable - option.total_delivery_hours;
    reasons.push(`delivery margin is only ${formatHours(margin)} (${Math.round((margin / hoursAvailable) * 100)}% of the window)`);
  }
  if (noBackup) {
    reasons.push("no backup option exists — this was the only feasible candidate");
  }

  return (
    <div className="risk-flag" role="alert">
      <span className="risk-flag__icon" aria-hidden="true">⚠</span>
      <div className="risk-flag__body">
        <div className="risk-flag__title">Low margin — recommend monitoring closely</div>
        <div className="risk-flag__detail">{reasons.join("; ")}.</div>
      </div>
    </div>
  );
}

// --- Main card -------------------------------------------------------------

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

  const arrival = stringAt(action?.result, "shipment", "expected_arrival");
  const { verdict, marginHours } = compareToDeadline(arrival, deadline);

  const deliveryFits =
    option !== null && run.plan !== null
      ? option.total_delivery_hours <= run.plan.hours_available
      : null;

  // Plain-language lead
  const leadText =
    run.outcome === "resolved"
      ? option
        ? `The agent ordered ${formatNumber(option.quantity)} units from ${option.label} — arriving ${
            verdict === "on_time" && marginHours !== null
              ? `${formatHours(marginHours)} before the deadline`
              : formatDateTime(arrival)
          }.`
        : "The agent resolved the constraint."
      : run.outcome === "no_action_needed"
        ? "Everything was already fine — the agent checked and changed nothing."
        : meta.blurb;

  const allOptions = run.plan?.options ?? [];
  const allExcluded = run.plan?.excluded ?? [];
  const hasCandidates = allOptions.length > 0 || allExcluded.length > 0;

  return (
    <section className="card" aria-labelledby="outcome-heading">
      <header className="card__header">
        <h2 id="outcome-heading">Outcome</h2>
        <div className="card__header-meta">
          <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
          {/* D: Download audit report */}
          <button
            type="button"
            className="button button--ghost"
            style={{ fontSize: "0.8rem" }}
            aria-label="Download audit report as Markdown"
            onClick={() => downloadAuditReport(run)}
          >
            ↓ Audit report
          </button>
        </div>
      </header>

      <p className={`lead lead--${meta.tone}`}>{leadText}</p>

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

          {/* G: Risk flag — shown only when margin is thin or no backup exists */}
          {run.plan ? (
            <RiskFlag
              option={option}
              hoursAvailable={run.plan.hours_available}
              feasibleCount={allOptions.length}
            />
          ) : null}
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
          value={run.verify ? (run.verify.satisfied ? "Covered" : "Short") : "Not checked"}
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

      {/* A: Full candidate table */}
      {hasCandidates ? (
        <CandidateTable
          options={allOptions}
          excluded={allExcluded}
          selectedReferenceId={option?.reference_id ?? null}
        />
      ) : null}

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

      <p className="card__note">
        Score {option ? formatDecimal(option.score, 2) : "—"} is the optimizer&apos;s weighted
        blend of normalized cost, delivery time and carbon — lower is better. The count of
        excluded candidates is {formatNumber(run.plan?.excluded.length ?? 0)}.
        {numberAt(action?.result, "vendor_available_before") !== null
          ? ` Vendor stock moved from ${formatNumber(
              numberAt(action?.result, "vendor_available_before"),
            )} to ${formatNumber(numberAt(action?.result, "vendor", "available_quantity"))}.`
          : ""}
      </p>
    </section>
  );
}
