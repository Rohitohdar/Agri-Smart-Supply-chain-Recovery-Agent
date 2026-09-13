/**
 * Display formatting.
 *
 * One note on money: the backend stores `price_per_unit` as a bare number and
 * has no currency concept at all. The console therefore formats costs with a
 * symbol chosen for display only (`VITE_CURRENCY_SYMBOL`, default "₹") rather
 * than pretending the API carries a currency. No conversion ever happens here.
 */

const CURRENCY = import.meta.env.VITE_CURRENCY_SYMBOL?.trim() || "₹";

/** A grouped integer, e.g. 1470 -> "1,470". */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(value).toLocaleString("en-IN");
}

/** A grouped number that keeps one decimal when it is not whole. */
export function formatDecimal(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? formatNumber(value) : value.toFixed(digits);
}

/** Money, e.g. 19950 -> "₹19,950". */
export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${CURRENCY}${formatDecimal(value, 2)}`;
}

/**
 * A duration in hours, shown in days once it stops being readable.
 *
 * Rounded to a tenth *before* splitting, so 71.99 h reads "3 d" rather than the
 * absurd "2 d 24 h" that rounding the remainder afterwards produces.
 */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "—";
  const rounded = Math.round(hours * 10) / 10;
  if (rounded < 24) return `${formatDecimal(rounded)} h`;
  const days = Math.floor(rounded / 24);
  const rest = Math.round((rounded - days * 24) * 10) / 10;
  return rest === 0 ? `${days} d` : `${days} d ${formatDecimal(rest)} h`;
}

/** Carbon as the backend reports it — a plain weight in kg, no invented units. */
export function formatCarbon(kg: number | null | undefined): string {
  if (kg === null || kg === undefined || Number.isNaN(kg)) return "—";
  return `${formatDecimal(kg, 1)} kg`;
}

/** A short local clock time. The backend sends naive UTC, so it is read as UTC. */
export function formatClock(iso: string | null | undefined): string {
  const date = parseUtc(iso);
  if (!date) return "—";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** A local date and time. */
export function formatDateTime(iso: string | null | undefined): string {
  const date = parseUtc(iso);
  if (!date) return "—";
  return date.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The backend stores naive UTC (see its design notes), so a bare timestamp has
 * no zone. Appending one tells the browser how to render it in local time
 * instead of silently treating it as local.
 */
function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const normalised = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalised);
  return Number.isNaN(date.getTime()) ? null : date;
}

export { parseUtc };

/** "in 3 d 4 h" / "2 h ago" — for deadlines and freshness stamps. */
export function formatRelative(iso: string | null | undefined, now = new Date()): string {
  const date = parseUtc(iso);
  if (!date) return "—";
  const deltaHours = (date.getTime() - now.getTime()) / 3_600_000;
  const magnitude = Math.abs(deltaHours);
  const spoken =
    magnitude < 1
      ? `${Math.round(magnitude * 60)} min`
      : formatHours(magnitude);
  return deltaHours >= 0 ? `in ${spoken}` : `${spoken} ago`;
}

export type DeadlineVerdict = "on_time" | "late" | "unknown";

/**
 * Whether an arrival lands before a deadline, using only the two timestamps the
 * backend supplied. Nothing is estimated.
 */
export function compareToDeadline(
  arrivalIso: string | null | undefined,
  deadlineIso: string | null | undefined,
): { verdict: DeadlineVerdict; marginHours: number | null } {
  const arrival = parseUtc(arrivalIso);
  const deadline = parseUtc(deadlineIso);
  if (!arrival || !deadline) return { verdict: "unknown", marginHours: null };
  const marginHours = (deadline.getTime() - arrival.getTime()) / 3_600_000;
  return { verdict: marginHours >= 0 ? "on_time" : "late", marginHours };
}

/** A 0–1 ratio as a rounded percentage string. */
export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export { CURRENCY };
