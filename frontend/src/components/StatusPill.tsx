import type { ReactNode } from "react";

import type { Tone } from "../lib/describe";

/**
 * The single color vocabulary of the console, so the same state always reads the
 * same way: green healthy, amber degraded or advisory, red broken, blue neutral
 * information, grey inert.
 */
export function StatusPill({
  tone,
  children,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`pill pill--${tone}`} title={title}>
      {children}
    </span>
  );
}

export function statusTone(options: {
  violated: boolean;
  activeDisruptions: number;
}): Tone {
  if (options.violated) return "danger";
  if (options.activeDisruptions > 0) return "warn";
  return "ok";
}

export function statusLabel(options: {
  violated: boolean;
  activeDisruptions: number;
}): string {
  if (options.violated) return "Constraint violated";
  if (options.activeDisruptions > 0) return "Degraded";
  return "Healthy";
}
