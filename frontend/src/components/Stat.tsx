import type { ReactNode } from "react";

import type { Tone } from "../lib/describe";

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

/** A labelled horizontal bar, used for requirement coverage. */
export function Meter({
  value,
  max,
  tone = "info",
  caption,
}: {
  value: number;
  max: number;
  tone?: Tone;
  caption?: ReactNode;
}) {
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  return (
    <div className="meter">
      <div
        className="meter__track"
        role="progressbar"
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      {caption ? <div className="meter__caption">{caption}</div> : null}
    </div>
  );
}
