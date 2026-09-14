/**
 * The reasoning trace, in plain language.
 *
 * A judge should be able to read the agent's run without knowing what JSON is.
 * Every narrative here is derived from the step's own recorded result — the
 * numbers are read out of the payload that the tool actually returned, never
 * restated from memory or recalculated. The raw payload is still available
 * behind the "view details" toggle; this module only decides how to *say* it.
 */

import type {
  AgentOutcome,
  RankedOption,
  RecoveryPlan,
  ShipmentStatus,
  TraceStep,
} from "../api/types";
import {
  formatCarbon,
  formatCost,
  formatDateTime,
  formatDecimal,
  formatHours,
  formatNumber,
} from "./format";
import {
  asArray,
  asBoolean,
  asRecord,
  booleanAt,
  field,
  numberAt,
  stringAt,
  sumBy,
} from "./read";

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

export interface Narrative {
  index: number;
  tone: Tone;
  /** The phase, shown as a small tag so the loop is visible at a glance. */
  phase: string;
  title: string;
  detail: string | null;
  /** True for steps that changed state, so the feed can mark them. */
  isAction: boolean;
}

export function shipmentTone(status: ShipmentStatus): Tone {
  switch (status) {
    case "ARRIVED":
      return "ok";
    case "DELAYED":
      return "danger";
    case "CANCELLED":
      return "neutral";
    default:
      return "info";
  }
}

export function shipmentLabel(status: ShipmentStatus): string {
  const labels: Record<ShipmentStatus, string> = {
    PENDING: "Pending",
    IN_TRANSIT: "In transit",
    DELAYED: "Delayed",
    ARRIVED: "Arrived",
    CANCELLED: "Cancelled",
  };
  return labels[status];
}

/** Whether a shipment still counts towards supply. */
export function isShipmentActive(status: ShipmentStatus): boolean {
  return status !== "ARRIVED" && status !== "CANCELLED";
}

export function actionLabel(action: string): string {
  if (action === "warehouse_transfer") return "Warehouse transfer";
  if (action === "vendor_purchase") return "Vendor purchase";
  if (action === "transfer_inventory") return "Warehouse transfer";
  if (action === "purchase_from_vendor") return "Vendor purchase";
  if (action === "reroute_shipment") return "Shipment reroute";
  return action.replace(/_/g, " ");
}

export function toolLabel(tool: string): string {
  const labels: Record<string, string> = {
    get_demand: "Reading demand",
    get_shipments: "Reading shipments",
    get_routes: "Reading routes",
    get_vendors: "Checking vendors…",
    get_inventory: "Checking warehouse stock",
    optimize_recovery: "Optimizing",
    transfer_inventory: "Executing warehouse transfer",
    purchase_from_vendor: "Placing vendor order",
    reroute_shipment: "Rerouting shipment",
    verify_state: "Verifying",
  };
  return labels[tool] ?? tool.replace(/_/g, " ");
}

export const OUTCOME_META: Record<
  AgentOutcome,
  { tone: Tone; label: string; blurb: string }
> = {
  resolved: {
    tone: "ok",
    label: "Recovery complete",
    blurb: "The agent acted and re-checked: the requirement is covered.",
  },
  no_action_needed: {
    tone: "ok",
    label: "Nothing to fix",
    blurb: "Every constraint already held, so the agent changed nothing.",
  },
  no_feasible_option: {
    tone: "danger",
    label: "No feasible option",
    blurb: "Nothing available can meet the constraints, so the agent refused to guess.",
  },
  action_rejected: {
    tone: "warn",
    label: "Action refused",
    blurb: "The chosen action was refused and never retried, so the agent stopped.",
  },
  decision_rejected: {
    tone: "warn",
    label: "Blocked by a guardrail",
    blurb: "A safety guard refused the proposed action before any stock moved.",
  },
  replan_limit_reached: {
    tone: "warn",
    label: "Replan limit reached",
    blurb: "The agent replanned to its cap and stopped rather than loop.",
  },
  tool_call_limit_reached: {
    tone: "warn",
    label: "Tool budget exhausted",
    blurb: "The per-cycle tool-call budget ran out, so the agent stopped.",
  },
};

function count(value: unknown[]): number {
  return value.length;
}

/** Find the ranked option a decision refers to, so `decide` can quote its numbers. */
function optionFor(
  plan: RecoveryPlan | null,
  action: string | null,
  referenceId: number | null,
): RankedOption | null {
  if (!plan || !action || referenceId === null) return null;
  return plan.options.find(
    (option) => option.action === action && option.reference_id === referenceId,
  ) ?? null;
}

function describeObserve(step: TraceStep): Narrative {
  const base = { index: step.index, phase: step.phase, isAction: false } as const;

  if (step.tool === "get_demand") {
    const result = asRecord(step.result);
    const required = numberAt(result, "required_quantity");
    const available = numberAt(result, "available_quantity");
    const shortage = numberAt(result, "shortage");
    return {
      ...base,
      tone: "info",
      title: "Checked the dealer's requirement",
      detail:
        required === null
          ? null
          : `${formatNumber(required)} units needed by ${formatDateTime(
              stringAt(result, "deadline"),
            )} · ${formatNumber(available)} on hand · ${formatNumber(shortage)} short.`,
    };
  }

  if (step.tool === "get_shipments") {
    const shipments = asArray(step.result);
    return {
      ...base,
      tone: "info",
      title: "Checked shipments on the way",
      detail: `${formatNumber(count(shipments))} shipment(s) tracked · ${formatNumber(
        sumBy(shipments, "quantity"),
      )} units in total.`,
    };
  }

  if (step.tool === "get_routes") {
    const routes = asArray(step.result);
    const open = routes.filter((route) => asBoolean(field(route, "is_available")) !== false);
    return {
      ...base,
      tone: "info",
      title: "Checked the route network",
      detail: `${formatNumber(open.length)} of ${formatNumber(count(routes))} routes open.`,
    };
  }

  return {
    ...base,
    tone: "info",
    title: step.tool ? toolLabel(step.tool) : "Observing",
    detail: null,
  };
}

function describeDetect(step: TraceStep): Narrative {
  const result = asRecord(step.result);
  const violated = booleanAt(result, "constraint_violated") ?? false;
  const shortage = numberAt(result, "shortage");
  const violations = asArray(result?.constraint_violations).filter(
    (item): item is string => typeof item === "string",
  );

  if (!violated) {
    return {
      index: step.index,
      phase: step.phase,
      tone: "ok",
      title: "No action needed",
      detail: "The constraint check came back clean, so the agent stopped here.",
      isAction: false,
    };
  }

  return {
    index: step.index,
    phase: step.phase,
    tone: "danger",
    title: "Constraint violated — investigating recovery",
    detail:
      violations.length > 0
        ? `${violations.join("; ")}.`
        : `Short by ${formatNumber(shortage)} units.`,
    isAction: false,
  };
}

function describeInvestigate(step: TraceStep): Narrative {
  const base = { index: step.index, phase: step.phase, isAction: false } as const;

  if (step.tool === "get_vendors") {
    const vendors = asArray(step.result);
    const available = vendors.filter(
      (vendor) => asBoolean(field(vendor, "is_available")) !== false,
    );
    const prices = available
      .map((vendor) => numberAt(vendor, "price_per_unit"))
      .filter((price): price is number => price !== null);
    const cheapest = prices.length > 0 ? Math.min(...prices) : null;
    const firstAvailable = asRecord(available.at(0));
    const unit = stringAt(firstAvailable, "unit");
    return {
      ...base,
      tone: "info",
      title: "Checking vendors…",
      detail: `${formatNumber(available.length)} of ${formatNumber(
        count(vendors),
      )} vendors available · cheapest ${formatCost(cheapest)}${unit ? ` per ${unit}` : ""}.`,
    };
  }

  if (step.tool === "get_inventory") {
    const warehouses = asArray(asRecord(step.result)?.warehouses);
    const total = numberAt(step.result, "total_quantity");
    return {
      ...base,
      tone: "info",
      title: "Checking warehouse stock",
      detail: `${formatNumber(count(warehouses))} warehouses · ${formatNumber(
        total,
      )} units across all locations.`,
    };
  }

  if (step.tool === "get_routes") {
    const routes = asArray(step.result);
    const open = routes.filter((route) => asBoolean(field(route, "is_available")) !== false);
    return {
      ...base,
      tone: "info",
      title: "Re-checking routes for a viable delivery",
      detail: `${formatNumber(open.length)} of ${formatNumber(count(routes))} routes open.`,
    };
  }

  return {
    ...base,
    tone: "info",
    title: step.tool ? toolLabel(step.tool) : "Investigating",
    detail: null,
  };
}

function describePlan(feasibleCount: number, excludedCount: number): string {
  if (feasibleCount === 0) {
    return `${formatNumber(excludedCount)} candidate(s) checked and ruled out — nothing can cover the shortfall in time.`;
  }
  const parts = [`${formatNumber(feasibleCount)} feasible option(s) found`];
  if (excludedCount > 0) parts.push(`${formatNumber(excludedCount)} ruled out`);
  return `${parts.join(" · ")}.`;
}

function describeOptimize(step: TraceStep): Narrative {
  const record = asRecord(step.result);
  const options = asArray(record?.options);
  const excluded = asArray(record?.excluded);
  const feasible = options.length > 0;
  const top = asRecord(options.at(0));
  const topAction = top ? stringAt(top, "action") : null;

  return {
    index: step.index,
    phase: step.phase,
    tone: feasible ? "ok" : "danger",
    title: feasible
      ? `Optimizer ranked ${formatNumber(options.length)} option(s)${
          topAction ? ` — top: ${actionLabel(topAction)}` : ""
        }`
      : "No feasible option found",
    detail: describePlan(options.length, excluded.length),
    isAction: false,
  };
}

function describeDecide(step: TraceStep, plan: RecoveryPlan | null): Narrative {
  const result = asRecord(step.result);
  const action = stringAt(result, "action");
  const referenceId = numberAt(result, "params", "reference_id");
  const option = optionFor(plan, action, referenceId);
  const reasoning = stringAt(result, "reasoning");

  if (!action) {
    return {
      index: step.index,
      phase: step.phase,
      tone: "warn",
      title: "No action could be authorised",
      detail: reasoning,
      isAction: false,
    };
  }

  return {
    index: step.index,
    phase: step.phase,
    tone: "info",
    title: `Selected: ${actionLabel(action)}${option ? ` — ${option.label}` : ""}`,
    detail: option
      ? `${formatNumber(option.quantity)} units · ${formatCost(option.total_cost)} · ${formatHours(
          option.total_delivery_hours,
        )} · ${formatCarbon(option.total_carbon)}${
          option.single_feasible_option
            ? " · Only one feasible option met the constraints — shown with raw metrics, not a comparative score."
            : ` · score ${formatDecimal(option.score, 2)}`
        }.`
      : reasoning,
    isAction: true,
  };
}

function describeExecute(step: TraceStep): Narrative {
  const base = { index: step.index, phase: step.phase } as const;
  const failed = step.note !== null && step.note.startsWith("refused");

  if (failed) {
    return {
      ...base,
      tone: "danger",
      title: "Action refused",
      detail: step.note,
      isAction: true,
    };
  }

  const result = step.result;

  if (step.tool === "purchase_from_vendor") {
    const vendorName = stringAt(result, "vendor", "name");
    const shipmentId = numberAt(result, "shipment", "id");
    const quantity = numberAt(result, "shipment", "quantity");
    const arrival = stringAt(result, "shipment", "expected_arrival");
    const before = numberAt(result, "vendor_available_before");
    const after = numberAt(result, "vendor", "available_quantity");
    return {
      ...base,
      tone: "ok",
      title: `Ordered from ${vendorName ?? "the vendor"}`,
      detail: `Shipment #${shipmentId ?? "—"} of ${formatNumber(quantity)} units arrives ${formatDateTime(
        arrival,
      )} · vendor stock ${formatNumber(before)} → ${formatNumber(after)}.`,
      isAction: true,
    };
  }

  if (step.tool === "transfer_inventory") {
    const quantity = numberAt(result, "quantity");
    const sourceBefore = numberAt(result, "source_before", "total_quantity");
    const sourceAfter = numberAt(result, "source_after", "total_quantity");
    const destBefore = numberAt(result, "destination_before", "total_quantity");
    const destAfter = numberAt(result, "destination_after", "total_quantity");
    return {
      ...base,
      tone: "ok",
      title: `Moved ${formatNumber(quantity)} units`,
      detail: `Source ${formatNumber(sourceBefore)} → ${formatNumber(
        sourceAfter,
      )} · destination ${formatNumber(destBefore)} → ${formatNumber(destAfter)}.`,
      isAction: true,
    };
  }

  if (step.tool === "reroute_shipment") {
    const shipmentId = numberAt(result, "shipment", "id");
    const arrival = stringAt(result, "shipment", "expected_arrival");
    return {
      ...base,
      tone: "ok",
      title: `Rerouted shipment #${shipmentId ?? "—"}`,
      detail: `Now arrives ${formatDateTime(arrival)}.`,
      isAction: true,
    };
  }

  return {
    ...base,
    tone: "ok",
    title: step.tool ? toolLabel(step.tool) : "Executed",
    detail: null,
    isAction: true,
  };
}

function describeVerify(step: TraceStep): Narrative {
  const result = asRecord(step.result);
  const satisfied = booleanAt(result, "satisfied") ?? false;
  const covered = numberAt(result, "covered_quantity");
  const required = numberAt(result, "required_quantity");
  const onHand = numberAt(result, "available_quantity");
  const inbound = numberAt(result, "on_time_inbound_quantity");
  const late = asArray(result?.late_shipment_ids);
  const stillViolated = booleanAt(result, "constraint_violated") ?? false;

  const sentences = [
    `${formatNumber(covered)} of ${formatNumber(required)} covered (${formatNumber(
      onHand,
    )} on hand + ${formatNumber(inbound)} inbound by the deadline).`,
  ];
  if (late.length > 0) {
    sentences.push(`Arriving late: shipment(s) ${late.join(", ")}.`);
  }
  if (satisfied && stillViolated) {
    // The backend reports both, and they legitimately disagree: on-hand stock can
    // be short while inbound shipments already cover the requirement.
    sentences.push(
      "Note: stock on hand is still below the requirement — the shortfall is covered by deliveries already on the way.",
    );
  }

  return {
    index: step.index,
    phase: step.phase,
    tone: satisfied ? "ok" : "warn",
    title: satisfied ? "Verified: requirement covered ✅" : "Verified: still short ⚠",
    detail: sentences.join(" "),
    isAction: false,
  };
}

function describeGuardrail(step: TraceStep): Narrative {
  const grounding = asRecord(step.result);
  const rejected = asArray(grounding?.rejected_numbers);
  const regenerated = asBoolean(grounding?.regenerated) ?? false;
  const fallback = asBoolean(grounding?.fallback_used) ?? false;
  const attempts = numberAt(grounding, "attempts");
  const fallbackReason = stringAt(grounding, "fallback_reason");

  if (grounding && rejected.length > 0) {
    return {
      index: step.index,
      phase: step.phase,
      tone: "warn",
      title: "Safety check: an ungrounded number was caught",
      detail: `The explanation cited ${rejected
        .flat()
        .join(", ")}, which no tool returned, so it was discarded and rewritten${
        fallback ? " from the template" : ""
      } (${formatNumber(attempts)} attempt(s)).`,
      isAction: false,
    };
  }

  if (fallback && fallbackReason) {
    // The template wrote the summary. Say why, so an LLM outage reads as an LLM
    // outage rather than as "the agent got quieter".
    return {
      index: step.index,
      phase: step.phase,
      tone: "warn",
      title: "Summary written by the built-in template",
      detail: `The language model did not write it: ${fallbackReason}. Every figure below still comes from the tool results.`,
      isAction: false,
    };
  }

  if (grounding) {
    return {
      index: step.index,
      phase: step.phase,
      tone: "ok",
      title: "Safety checks passed",
      detail: `Explanation grounded in the tool results on the first attempt${
        regenerated ? " (regenerated)" : ""
      }.`,
      isAction: false,
    };
  }

  return {
    index: step.index,
    phase: step.phase,
    tone: step.note?.includes("No feasible") ? "danger" : "warn",
    title: "Guardrail",
    detail: step.note,
    isAction: false,
  };
}

/**
 * Turn a whole trace into narratives.
 *
 * Done for the whole array at once so the `decide` step can quote the metrics
 * from the `optimize` result it belongs to.
 */
export function describeTrace(trace: TraceStep[], plan: RecoveryPlan | null): Narrative[] {
  return trace.map((step) => {
    switch (step.phase) {
      case "observe":
        return describeObserve(step);
      case "detect":
        return describeDetect(step);
      case "investigate":
        return describeInvestigate(step);
      case "optimize":
        return describeOptimize(step);
      case "decide":
        return describeDecide(step, plan);
      case "execute":
        return describeExecute(step);
      case "verify":
        return describeVerify(step);
      case "guardrail":
        return describeGuardrail(step);
      default:
        return {
          index: step.index,
          phase: step.phase,
          tone: "neutral" as Tone,
          title: step.tool ? toolLabel(step.tool) : step.phase,
          detail: step.note,
          isAction: false,
        };
    }
  });
}

