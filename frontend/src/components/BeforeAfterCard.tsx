import type { AgentRun, Demand } from "../api/types";
import { formatDateTime, formatHours, formatNumber } from "../lib/format";
import { compareToDeadline } from "../lib/format";
import { coverage, inboundByDeadline } from "../lib/supply";
import { stringAt } from "../lib/read";
import { JsonDetails } from "./JsonDetails";
import { StatusPill } from "./StatusPill";

/**
 * Pre- and post-recovery numbers.
 *
 * Worth knowing when reading this: a vendor purchase adds *inbound* supply, not
 * stock on hand, so the on-hand figures legitimately do not move. The card shows
 * that rather than hiding it, and the verdict row compares the backend's two
 * verdicts — `constraint_violated` before the run, `satisfied` after it.
 */
export function BeforeAfterCard({
  before,
  run,
}: {
  before: Demand | null;
  run: AgentRun | null;
}) {
  if (!before || !run) {
    return (
      <section className="card" aria-labelledby="before-after-heading">
        <header className="card__header">
          <h2 id="before-after-heading">Before / after</h2>
          <StatusPill tone="neutral">Not run yet</StatusPill>
        </header>
        <p className="muted">
          Run the agent and this card will compare the numbers from before the run with the
          numbers it saw when it verified its own work.
        </p>
      </section>
    );
  }

  const verify = run.verify;
  const after = verify?.demand ?? null;
  const beforeInbound = inboundByDeadline(before);
  const afterInbound = after ? inboundByDeadline(after) : null;

  const beforeCoverage = coverage(before);
  const afterCoverage = after ? coverage(after) : null;

  // Plain-language lead
  const leadText = verify?.satisfied
    ? `Recovery worked — the requirement is now covered by deliveries on the way.`
    : `The requirement is still short after the agent ran.`;
  const leadTone = verify?.satisfied ? "ok" : "warn";

  return (
    <section className="card" aria-labelledby="before-after-heading">
      <header className="card__header">
        <h2 id="before-after-heading">Before / after</h2>
        <StatusPill tone={verify?.satisfied ? "ok" : "warn"}>
          {verify?.satisfied ? "Requirement covered" : "Still short"}
        </StatusPill>
      </header>

      <p className={`lead lead--${leadTone}`}>{leadText}</p>

      <table className="table table--compare">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="num">Before</th>
            <th className="num">After</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          <CompareRow
            label="On hand"
            before={before.available_quantity}
            after={after?.available_quantity ?? null}
            note="a purchase arrives in transit, so on-hand stock does not move"
          />
          <CompareRow
            label="Inbound by deadline"
            before={beforeInbound.onTime}
            after={afterInbound?.onTime ?? null}
          />
          <CompareRow
            label="Coverage (on hand + inbound)"
            before={beforeCoverage}
            after={afterCoverage}
          />
          <CompareRow
            label="Requirement"
            before={before.required_quantity}
            after={after?.required_quantity ?? null}
            invert
          />
          <CompareRow
            label="Shortfall on hand"
            before={before.shortage}
            after={after?.shortage ?? null}
            invert
          />
        </tbody>
      </table>

      <div className="verdicts">
        <div className="verdict">
          <div className="verdict__label">Before the run</div>
          <StatusPill tone={before.constraint_violated ? "danger" : "ok"}>
            {before.constraint_violated ? "Constraint violated" : "Constraint held"}
          </StatusPill>
          <div className="verdict__hint">
            {before.constraint_violations.at(0) ?? "No violations reported"}
          </div>
        </div>
        <div className="verdict__arrow" aria-hidden="true">
          →
        </div>
        <div className="verdict">
          <div className="verdict__label">After the run</div>
          <StatusPill tone={verify?.satisfied ? "ok" : "warn"}>
            {verify
              ? verify.satisfied
                ? "Requirement covered"
                : "Requirement not covered"
              : "Not verified"}
          </StatusPill>
          <div className="verdict__hint">
            {verify
              ? `${formatNumber(verify.covered_quantity)} covered of ${formatNumber(
                  verify.required_quantity,
                )} required`
              : "No verification recorded"}
          </div>
        </div>
        <div className="verdict">
          <div className="verdict__label">Deadline</div>
          <div className="verdict__value">{formatDateTime(before.deadline)}</div>
        </div>
      </div>

      {verify && verify.satisfied && verify.constraint_violated ? (
        <p className="notice notice--warn">
          Both verdicts are true and they are not in conflict: the requirement is covered by
          deliveries already on the way, while stock on hand is still below it. The backend
          reports both so you can see the difference.
        </p>
      ) : null}

      {/* B: Baseline comparison — what if we did nothing */}
      {verify ? (
        <BaselineComparison before={before} run={run} />
      ) : null}

      <JsonDetails
        label="view raw demand before and after"
        value={{ before, after, verify }}
        summary="get_demand + verify_state"
      />
    </section>
  );
}

function CompareRow({
  label,
  before,
  after,
  note,
  invert = false,
}: {
  label: string;
  before: number | null;
  after: number | null;
  note?: string;
  /** For metrics where smaller is better (requirement, shortfall). */
  invert?: boolean;
}) {
  const delta = before !== null && after !== null ? after - before : null;
  const improved = delta === null ? null : invert ? delta <= 0 : delta >= 0;

  return (
    <tr>
      <th scope="row">
        {label}
        {note ? <span className="muted"> — {note}</span> : null}
      </th>
      <td className="num">{formatNumber(before)}</td>
      <td className="num">{formatNumber(after)}</td>
      <td className="num">
        {delta === null ? (
          "—"
        ) : delta === 0 ? (
          <span className="muted">no change</span>
        ) : (
          <span className={improved ? "delta delta--better" : "delta delta--worse"}>
            {delta > 0 ? "+" : "−"}
            {formatNumber(Math.abs(delta))}
          </span>
        )}
      </td>
    </tr>
  );
}

// --- B: Baseline comparison ------------------------------------------------

function BaselineComparison({ before, run }: { before: Demand; run: AgentRun }) {
  const verify = run.verify;
  const action = run.actions.at(0) ?? null;
  const arrival = stringAt(action?.result, "shipment", "expected_arrival");
  const { verdict, marginHours } = compareToDeadline(arrival, before.deadline);

  // "Without recovery" — the situation as it stood before the run.
  const beforeCoverage = coverage(before);
  const uncoveredShortfall = Math.max(before.required_quantity - beforeCoverage, 0);

  // Deadline miss: how far past the deadline the delayed shipment would have landed.
  // We use the first active shipment's ETA as the "do nothing" arrival.
  const worstShipment = before.active_shipments
    .filter((s) => s.expected_arrival !== null)
    .sort((a, b) =>
      new Date(b.expected_arrival!).getTime() - new Date(a.expected_arrival!).getTime()
    ).at(0);
  const { marginHours: doNothingMargin } = compareToDeadline(
    worstShipment?.expected_arrival,
    before.deadline,
  );

  const withRecovery = verify?.satisfied ?? false;

  return (
    <div className="block">
      <h3>What if the agent had done nothing?</h3>
      <div className="baseline">
        <div className="baseline__col baseline__col--bad">
          <div className="baseline__eyebrow">Without recovery</div>
          <div className="baseline__headline baseline__headline--bad">
            {uncoveredShortfall > 0
              ? `Short by ${formatNumber(uncoveredShortfall)} units`
              : "Coverage marginal"}
          </div>
          <div className="baseline__detail">
            {doNothingMargin !== null && doNothingMargin < 0
              ? `Deadline missed by ${formatHours(Math.abs(doNothingMargin))}`
              : doNothingMargin !== null
                ? `Latest shipment arrives ${formatHours(doNothingMargin)} before deadline`
                : "No shipment ETA recorded"}
          </div>
          <div className="baseline__detail">
            Coverage: {formatNumber(beforeCoverage)} of {formatNumber(before.required_quantity)} required
          </div>
        </div>

        <div className="baseline__arrow" aria-hidden="true">→</div>

        <div className="baseline__col baseline__col--good">
          <div className="baseline__eyebrow">With recovery</div>
          <div className={`baseline__headline baseline__headline--${withRecovery ? "good" : "bad"}`}>
            {withRecovery ? "Fully covered" : "Still short"}
          </div>
          <div className="baseline__detail">
            {verdict === "on_time" && marginHours !== null
              ? `Arrives ${formatHours(marginHours)} before the deadline`
              : verdict === "late" && marginHours !== null
                ? `Arrives ${formatHours(Math.abs(marginHours))} after the deadline`
                : verify
                  ? `${formatNumber(verify.covered_quantity)} of ${formatNumber(verify.required_quantity)} covered`
                  : "No arrival recorded"}
          </div>
          {verify ? (
            <div className="baseline__detail">
              Coverage: {formatNumber(verify.covered_quantity)} of {formatNumber(verify.required_quantity)} required
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
