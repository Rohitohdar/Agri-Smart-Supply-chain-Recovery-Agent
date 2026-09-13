/**
 * Tiny safe accessors for the agent's raw tool results.
 *
 * The trace stores each tool's output as `unknown` because it genuinely is: any
 * tool's payload can appear there. These helpers read it defensively so a shape
 * change degrades to "—" instead of throwing inside a render. They only ever
 * read values the backend sent — nothing is computed or inferred here.
 */

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function asBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

/** Read a nested field, e.g. `field(result, "to", "after")`. */
export function field(value: unknown, ...path: string[]): unknown {
  let current: unknown = value;
  for (const key of path) {
    const record = asRecord(current);
    if (!record) return undefined;
    current = record[key];
  }
  return current;
}

export function numberAt(value: unknown, ...path: string[]): number | null {
  return asNumber(field(value, ...path));
}

export function stringAt(value: unknown, ...path: string[]): string | null {
  return asString(field(value, ...path));
}

/**
 * Read a nested boolean.
 *
 * Its own accessor on purpose: `numberAt` on a boolean field returns null, and
 * silently reading `constraint_violated` as a number once made the console claim
 * the opposite of what the backend reported.
 */
export function booleanAt(value: unknown, ...path: string[]): boolean | null {
  return asBoolean(field(value, ...path));
}

/** Sum a numeric field across an array, e.g. shipment quantities. */
export function sumBy(values: unknown[], ...path: string[]): number {
  return values.reduce<number>((total, item) => total + (numberAt(item, ...path) ?? 0), 0);
}

/** Key/value pairs of an object, for the raw-details table. */
export function entries(value: unknown): Array<[string, unknown]> {
  const record = asRecord(value);
  return record ? Object.entries(record) : [];
}

/** A compact one-line rendering of any JSON value, for list rows. */
export function inline(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  try {
    const text = JSON.stringify(value);
    return text.length > 160 ? `${text.slice(0, 157)}…` : text;
  } catch {
    return String(value);
  }
}
