/**
 * Line art and icons. One stroke vocabulary — round caps, ~1.4px at icon size —
 * so the emblems, sketches and controls read as drawn by the same hand.
 */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const line = {
  fill: "none",
  stroke: "currentColor",
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

/** Round emblem: a seedling over hills and three furrows, ringed. */
export function Emblem(props: IconProps) {
  return (
    <svg viewBox="0 0 80 80" aria-hidden="true" {...props}>
      <circle cx="40" cy="40" r="37" {...line} strokeWidth="2" />
      <g {...line} strokeWidth="2.2">
        <path d="M40 34V14" />
        <path d="M40 22c-6 0-9-4-9-8 6 0 9 3 9 8z" fill="currentColor" />
        <path d="M40 26c6 0 10-4 10-9-7 0-10 4-10 9z" fill="currentColor" />
      </g>
      <path
        d="M9 48l14-12 9 7 8-9 13 11 6-4 12 10v8H9z"
        fill="currentColor"
      />
      <g {...line} strokeWidth="3" stroke="var(--paper-hi)">
        <path d="M10 56c10-4 20-4 30 0s20 4 30 0" />
        <path d="M12 63c9-3 18-3 28 0s19 3 28 0" />
      </g>
      <path d="M14 69c8-2 17-2 26 0s18 2 26 0" {...line} strokeWidth="2.6" />
    </svg>
  );
}

/** Square-framed mark: a brushed canopy over a storehouse roof. */
export function FramedMark(props: IconProps) {
  return (
    <svg viewBox="0 0 120 100" aria-hidden="true" {...props}>
      <path d="M8 6h86v6M8 6v86h40" fill="none" stroke="var(--olive)" strokeWidth="7" />
      <path
        d="M30 58c-14-4-14-24 2-26 0-14 18-20 28-10 10-12 30-6 30 8 14 0 18 18 6 24 2 12-14 16-22 8-6 8-22 8-26-2-8 4-18 2-18-2z"
        fill="var(--olive-bright)"
        filter="url(#bristle)"
      />
      <path d="M50 92V70l26-20 30 24" fill="none" stroke="var(--ink)" strokeWidth="5" strokeLinejoin="miter" />
      <rect x="72" y="70" width="12" height="12" fill="var(--olive)" />
      <path d="M78 70v12M72 76h12" stroke="var(--paper-hi)" strokeWidth="1.6" />
    </svg>
  );
}

/** Small tree emblem used above the dealer block. */
export function TreeMark(props: IconProps) {
  return (
    <svg viewBox="0 0 60 50" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.3">
        <path d="M30 48V26M30 34l-7-6M30 31l8-7M30 28l-4-8M30 27l5-9" />
        <path d="M8 48h44" />
      </g>
      <g fill="currentColor">
        {[
          [30, 9, 8],
          [19, 15, 7],
          [41, 15, 7],
          [13, 24, 6],
          [47, 24, 6],
          [24, 21, 6],
          [36, 21, 6],
        ].map(([cx, cy, r]) => (
          <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} opacity="0.9" />
        ))}
      </g>
    </svg>
  );
}

/** Mountain-and-sun wordmark glyph for the collage header. */
export function RidgeMark(props: IconProps) {
  return (
    <svg viewBox="0 0 48 26" aria-hidden="true" {...props}>
      <path d="M2 24L16 8l7 8 6-6 17 14z" fill="var(--terracotta)" />
      <path d="M16 8l4 4.6L16 12l-3 2" fill="var(--paper-hi)" opacity="0.7" />
      <path d="M2 24h44" stroke="var(--ink)" strokeWidth="1.2" />
    </svg>
  );
}

export function Leaf(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.4">
        <path d="M5 19C5 10 10 5 19 5c0 9-5 14-14 14z" />
        <path d="M5 19l9-9" />
      </g>
    </svg>
  );
}

export function Storehouse(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.4">
        <path d="M3 10l9-6 9 6" />
        <path d="M5 9v11h14V9" />
        <path d="M9 20v-6h6v6M9 17h6" />
      </g>
    </svg>
  );
}

export function Pin(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.4">
        <path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0113 0c0 5-6.5 11-6.5 11z" />
        <circle cx="12" cy="10" r="2.3" />
      </g>
    </svg>
  );
}

export function ShieldCheck(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.4">
        <path d="M12 3l7 3v5c0 5-3 8.5-7 10-4-1.5-7-5-7-10V6z" />
        <path d="M9 12l2 2 4-4" />
      </g>
    </svg>
  );
}

export function Ridges(props: IconProps) {
  return (
    <svg viewBox="0 0 28 20" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.4">
        <path d="M1 18l8-11 5 6 4-4 9 9z" />
        <path d="M9 7l2 3" />
      </g>
    </svg>
  );
}

export function Arrow(props: IconProps) {
  return (
    <svg viewBox="0 0 20 12" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.4">
        <path d="M1 6h17M13 1l5 5-5 5" />
      </g>
    </svg>
  );
}

/** Sprig flanked by rules — the divider under the poster title. */
export function SprigRule(props: IconProps) {
  return (
    <svg viewBox="0 0 160 14" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1">
        <path d="M2 7h58M100 7h58" />
        <path d="M66 7h28" />
        <path d="M72 7c2-4 6-4 7-4-1 3-4 4-7 4zM72 7c2 4 6 4 7 4-1-3-4-4-7-4zM82 7c2-4 6-4 7-4-1 3-4 4-7 4zM82 7c2 4 6 4 7 4-1-3-4-4-7-4z" fill="currentColor" />
      </g>
    </svg>
  );
}

/** Three birds in flight, each its own colour. */
export function Birds(props: IconProps) {
  return (
    <svg viewBox="0 0 140 90" aria-hidden="true" {...props}>
      <path d="M8 40c8-10 14-12 22-6 4-12 12-18 20-18-6 6-8 14-10 22 6 0 12 4 14 8-10-4-22-2-30 2-6-6-10-8-16-8z" fill="var(--terracotta)" />
      <path d="M86 18c6-6 10-8 16-4 4-8 10-12 16-12-4 4-6 10-8 15 5 0 9 3 10 6-8-3-16-1-22 2-4-5-8-7-12-7z" fill="var(--sage)" />
      <path d="M70 70c4-4 7-5 11-2 2-6 6-8 10-8-3 3-4 7-5 10 3 0 6 2 7 4-5-2-10-1-14 1-3-3-6-5-9-5z" fill="var(--ochre)" />
    </svg>
  );
}

/** Pencil sketch: granary with silo and two trees on a rise. */
export function GranarySketch(props: IconProps) {
  return (
    <svg viewBox="0 0 200 120" aria-hidden="true" {...props}>
      <g {...line} strokeWidth="1.1" stroke="var(--ink-soft)">
        <path d="M6 108c30-14 70-16 120-10s60 6 70 8" />
        <path d="M18 112c40-6 90-6 150-2" opacity="0.6" />
        <path d="M70 100V66l26-16 26 16v34" />
        <path d="M64 70l32-22 32 22" />
        <path d="M86 100V82h20v18M86 88h20" />
        <path d="M132 100V52a10 10 0 0120 0v48M132 60h20M132 72h20M132 84h20" />
        <path d="M128 52l14-12 14 12" />
        <path d="M30 100V62M44 100V70" />
        <path d="M30 62c-10 6-12 18-2 22h6c8-6 6-18-4-22z" fill="var(--sage-pale)" />
        <path d="M44 66c-8 6-9 16-1 20h4c6-5 5-15-3-20z" fill="var(--sage-pale)" />
        <path d="M76 80h4M76 88h4M114 80h4M114 88h4" />
      </g>
    </svg>
  );
}

/** Pencil sketch: a laden truck on the road, hills behind. */
export function TruckSketch(props: IconProps) {
  return (
    <svg viewBox="0 0 260 90" aria-hidden="true" {...props}>
      <path d="M0 70c30-20 60-24 90-12s50 12 70 0 60-26 100-6v18H0z" fill="var(--sage-pale)" />
      <path d="M150 58c20-14 50-20 110-6v14H150z" fill="var(--sage-soft)" />
      <g {...line} strokeWidth="1.2" stroke="var(--ink-soft)">
        <path d="M2 82h256" />
        <path d="M70 72V48h52v24M122 56h16l8 10v6h-24" />
        <path d="M128 58h8l5 7h-13z" />
        <circle cx="84" cy="74" r="5" fill="var(--paper)" />
        <circle cx="134" cy="74" r="5" fill="var(--paper)" />
        <path d="M74 48l6-8h8l6 8M96 48l6-8h8l6 8" />
      </g>
      <path d="M74 48l6-8h8l6 8zM96 48l6-8h8l6 8z" fill="var(--ochre)" opacity="0.55" />
      <g {...line} strokeWidth="1.1" stroke="var(--ink-soft)">
        <path d="M188 82V62M188 66l-6 8M188 66l5 7M188 72l-4 10M188 72l4 10" />
        <circle cx="188" cy="58" r="3" />
        <path d="M182 56c3-3 9-3 12 0" />
        <path d="M196 64l10 18" />
      </g>
    </svg>
  );
}
