import type { ReactNode } from "react";

import type { Tone } from "../lib/describe";
import { formatNumber } from "../lib/format";

/** One labelled metric. Big number, small label — no paragraphs. */
export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={`stat stat--${tone}`}>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {hint ? <div className="stat__hint">{hint}</div> : null}
    </div>
  );
}

/**
 * Requirement coverage drawn as strata: stock on hand, then supply that lands
 * before the deadline, then whatever is still missing, all against a tick at
 * the requirement. Every width is one of the backend's own quantities.
 */
export function CoverageStrata({
  onHand,
  inbound,
  required,
}: {
  onHand: number;
  inbound: number;
  required: number;
}) {
  const scale = Math.max(required, onHand + inbound, 1);
  const pct = (value: number) => `${(Math.max(value, 0) / scale) * 100}%`;
  const gap = Math.max(required - onHand - inbound, 0);
  const covered = Math.min(onHand + inbound, required);

  return (
    <figure className="strata">
      <div
        className="strata__bar"
        role="img"
        aria-label={`${formatNumber(covered)} of ${formatNumber(required)} required units covered`}
      >
        <span className="strata__seg strata__seg--onhand" style={{ width: pct(onHand) }} />
        <span className="strata__seg strata__seg--inbound" style={{ width: pct(inbound) }} />
        <span className="strata__seg strata__seg--gap" style={{ width: pct(gap) }} />
        <span className="strata__req" style={{ left: pct(required) }} aria-hidden="true" />
      </div>
      <figcaption className="strata__legend">
        <span><i className="key key--onhand" />On hand <b>{formatNumber(onHand)}</b></span>
        <span><i className="key key--inbound" />Inbound in time <b>{formatNumber(inbound)}</b></span>
        {gap > 0 ? (
          <span><i className="key key--gap" />Uncovered <b>{formatNumber(gap)}</b></span>
        ) : null}
        <span className="strata__legend-req"><i className="key key--req" />Requirement <b>{formatNumber(required)}</b></span>
      </figcaption>
    </figure>
  );
}
