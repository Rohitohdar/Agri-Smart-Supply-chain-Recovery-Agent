import type { AgentRun, Demand } from "../api/types";
import { formatDateTime, formatNumber } from "../lib/format";
import { coverage, inboundByDeadline } from "../lib/supply";
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

  return (
    <section className="card" aria-labelledby="before-after-heading">
      <header className="card__header">
        <h2 id="before-after-heading">Before / after</h2>
        <StatusPill tone={verify?.satisfied ? "ok" : "warn"}>
          {verify?.satisfied ? "Requirement covered" : "Still short"}
        </StatusPill>
      </header>

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
