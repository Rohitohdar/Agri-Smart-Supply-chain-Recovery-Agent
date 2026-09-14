/**
 * Hand-written mirrors of the backend's Pydantic response models.
 *
 * These are transcribed from the live API, not from the route decorators, so
 * they describe what the server actually returns. Every field the UI reads is
 * named here; nothing is guessed. Field names are kept snake_case exactly as
 * the backend emits them, so a mismatch is a compile error rather than a silent
 * `undefined` at runtime.
 */

// --- meta ------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  environment: string;
  /** False means the backend accepts writes without a key (development mode). */
  writes_authenticated: boolean;
  time: string;
}

export type Actor = "agent" | "system";

export interface AuditEntry {
  id: number;
  timestamp: string;
  actor: Actor;
  action_type: string;
  details: Record<string, unknown>;
  result: string;
}

export interface AdminState {
  counts: Record<string, number>;
  warehouse_inventory: Record<string, Record<string, number>>;
}

export interface ToolSpec {
  name: string;
  description: string;
  endpoint: string;
}

// --- supply chain ----------------------------------------------------------

export type ShipmentStatus =
  | "PENDING"
  | "IN_TRANSIT"
  | "DELAYED"
  | "ARRIVED"
  | "CANCELLED";

export interface Shipment {
  id: number;
  product_id: number;
  from_id: number;
  to_id: number;
  quantity: number;
  status: ShipmentStatus;
  expected_arrival: string | null;
  actual_arrival: string | null;
  delay_hours: number;
}

export interface Route {
  id: number;
  from_location_id: number;
  to_location_id: number;
  distance_km: number;
  travel_time_hours: number;
  carbon_per_km: number;
  is_available: boolean;
  /** Backend-computed: distance_km * carbon_per_km. */
  carbon_emission: number;
}

export interface Demand {
  dealer_id: number;
  dealer_name: string;
  location: string;
  required_quantity: number;
  available_quantity: number;
  deadline: string;
  active_shipments: Shipment[];
  /** Raw gap in stock on hand; it does not determine overall health. */
  shortage: number;
  /** Self-documenting alias for the raw on-hand gap reported by the API. */
  on_hand_shortfall: number;
  /** On hand plus inbound shipments arriving by the deadline. */
  covered_quantity: number;
  active_shipment_quantity: number;
  constraint_violations: string[];
  constraint_violated: boolean;
}

export interface DealerRead {
  id: number;
  name: string;
  location: string;
  required_quantity: number;
  deadline: string;
  current_inventory: number;
  shortfall: number;
}

/** Inventory keys are JSON object keys, so they arrive as strings. */
export interface WarehouseStock {
  location_id: number;
  name: string;
  location: string;
  location_type: "warehouse";
  inventory: Record<string, number>;
  total_quantity: number;
}

export interface DealerStock {
  location_id: number;
  name: string;
  location: string;
  location_type: "dealer";
  current_inventory: number;
  total_quantity: number;
}

export interface InventoryOverview {
  generated_at: string;
  warehouses: WarehouseStock[];
  dealers: DealerStock[];
  total_quantity: number;
}

export interface Vendor {
  id: number;
  name: string;
  product_id: number;
  product_name: string;
  unit: string;
  price_per_unit: number;
  available_quantity: number;
  delivery_hours: number;
  carbon_per_unit: number;
  is_available: boolean;
}

// --- optimizer -------------------------------------------------------------

export type RecoveryActionKind = "warehouse_transfer" | "vendor_purchase" | "reroute_shipment";

export interface RankedOption {
  rank: number;
  action: RecoveryActionKind;
  reference_id: number;
  label: string;
  quantity: number;
  route_id: number | null;
  total_cost: number;
  total_delivery_hours: number;
  total_carbon: number;
  normalized_cost: number;
  normalized_delivery_hours: number;
  normalized_carbon: number;
  cost_contribution: number;
  delivery_contribution: number;
  carbon_contribution: number;
  score: number;
  /** True when this was the only candidate that survived filtering; score 0 is not a comparative rank. */
  single_feasible_option: boolean;
}

export interface ExcludedOption {
  action: RecoveryActionKind;
  reference_id: number;
  label: string;
  quantity: number;
  reason: string;
  available_quantity: number;
  delivery_hours: number | null;
  hours_available: number | null;
}

export interface RecoveryPlan {
  shortage_quantity: number;
  deadline: string;
  hours_available: number;
  weights: { cost: number; delivery_hours: number; carbon: number };
  options: RankedOption[];
  excluded: ExcludedOption[];
}

// --- agent -----------------------------------------------------------------

export type AgentOutcome =
  | "no_action_needed"
  | "resolved"
  | "no_feasible_option"
  | "action_rejected"
  | "decision_rejected"
  | "replan_limit_reached"
  | "tool_call_limit_reached";

export type AgentPhase =
  | "observe"
  | "detect"
  | "investigate"
  | "optimize"
  | "decide"
  | "execute"
  | "verify"
  | "guardrail";

export interface TraceStep {
  index: number;
  phase: AgentPhase;
  tool: string | null;
  arguments: Record<string, unknown>;
  /** The tool's raw JSON result, unmodified — what "view details" reveals. */
  result: unknown;
  note: string | null;
}

export interface GroundingReport {
  attempts: number;
  rejected_numbers: string[][];
  regenerated: boolean;
  fallback_used: boolean;
  /** Why the template wrote the summary instead of the model; null when it didn't. */
  fallback_reason: string | null;
}

export interface AgentAction {
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  error: string | null;
  reason: string | null;
  result: unknown;
}

export interface VerifyState {
  required_quantity: number;
  available_quantity: number;
  on_time_inbound_quantity: number;
  covered_quantity: number;
  satisfied: boolean;
  late_shipment_ids: number[];
  unknown_eta_shipment_ids: number[];
  constraint_violated: boolean;
  shortage: number;
  demand: Demand;
  routes: Route[];
}

export interface AgentRun {
  run_id: string;
  outcome: AgentOutcome;
  explanation: string;
  replan_cycles: number;
  tool_calls: number;
  grounding: GroundingReport | null;
  observed_demand: Demand;
  plan: RecoveryPlan | null;
  verify: VerifyState | null;
  actions: AgentAction[];
  audit_log_ids: number[];
  trace: TraceStep[];
}

// --- disruption triggers ---------------------------------------------------

export interface ShipmentDelayResponse {
  shipment: Shipment;
  delay_hours: number;
  previous_status: ShipmentStatus;
  previous_expected_arrival: string | null;
  audit_log_id: number;
}

export interface VendorFailureResponse {
  vendor: Vendor;
  previous_is_available: boolean;
  audit_log_id: number;
}

export interface RouteBlockResponse {
  route: Route;
  previous_is_available: boolean;
  audit_log_id: number;
}

export interface DemandSpikeResponse {
  dealer: DealerRead;
  previous_required_quantity: number;
  shortage_before: number;
  shortage_after: number;
  audit_log_id: number;
}

// --- debug / demo pre-check -----------------------------------------------

export type DisruptionTargetKind = "vendor_failure" | "route_block" | "shipment_delay";

export interface VendorDisruptionTarget {
  kind: "vendor_failure";
  vendor_id: number;
  vendor_name: string;
  endpoint: string;
  payload: Record<string, unknown>;
}

export interface RouteDisruptionTarget {
  kind: "route_block";
  route_id: number;
  endpoint: string;
  payload: Record<string, unknown>;
}

export interface ShipmentDisruptionTarget {
  kind: "shipment_delay";
  shipment_id: number;
  endpoint: string;
  payload: Record<string, unknown>;
}

export type DisruptionTarget =
  | VendorDisruptionTarget
  | RouteDisruptionTarget
  | ShipmentDisruptionTarget;

export interface WouldChooseResponse {
  shortage_quantity: number;
  deadline: string;
  hours_available: number;
  top_option: RankedOption | null;
  feasible_count: number;
  disruption_target: DisruptionTarget | null;
  demo_instruction: string;
}

/** The `disruption_injected` audit entry's `details`, discriminated on `disruption`. */
export type DisruptionDetails =
  | {
      disruption: "shipment_delay";
      shipment_id: number;
      delay_hours: number;
      status: { before: ShipmentStatus; after: ShipmentStatus };
      expected_arrival: { before: string | null; after: string | null };
      total_delay_hours: number;
    }
  | {
      disruption: "vendor_failure";
      vendor_id: number;
      vendor_name: string;
      is_available: { before: boolean; after: boolean };
    }
  | {
      disruption: "route_block";
      route_id: number;
      from_location_id: number;
      to_location_id: number;
      is_available: { before: boolean; after: boolean };
    }
  | {
      disruption: "demand_spike";
      dealer_id: number;
      required_quantity: { before: number; after: number };
      shortage: { before: number; after: number };
    };
