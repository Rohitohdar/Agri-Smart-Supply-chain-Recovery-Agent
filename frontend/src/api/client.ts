/**
 * The one place this app talks to the backend.
 *
 * Two rules are enforced here rather than trusted to callers:
 *
 * 1. **Every** network call goes through `request()`. No component imports
 *    `fetch`, and none is exported, so there is no path to an endpoint that
 *    bypasses this module.
 * 2. State-changing calls declare `auth: "required"`. The client then refuses to
 *    issue the request at all unless it can authenticate it — that is, unless
 *    the backend reports writes are unauthenticated (development demo mode) or a
 *    key is configured. The key is attached to authenticated requests as
 *    `X-API-Key`, which is the header `app/security.py` checks. A control panel
 *    therefore cannot "forget" the auth layer: the only way to reach an action
 *    endpoint is through a function that has already decided it may.
 *
 * The key itself is never hardcoded and never committed; it is typed by the
 * operator, kept in `localStorage`, and sent only to the configured API origin.
 */

import type {
  AdminState,
  AgentRun,
  AuditEntry,
  Demand,
  DemandSpikeResponse,
  HealthResponse,
  InventoryOverview,
  Route,
  RouteBlockResponse,
  Shipment,
  ShipmentDelayResponse,
  ToolSpec,
  Vendor,
  VendorFailureResponse,
} from "./types";

/** The header the backend's `require_api_key` dependency reads. */
export const API_KEY_HEADER = "X-API-Key";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

export interface ClientConfig {
  baseUrl: string;
  /** The operator's API key, or null when none has been entered. */
  apiKey: string | null;
  /** From `GET /health`: true when the backend rejects unauthenticated writes. */
  writesAuthenticated: boolean;
}

let config: ClientConfig = {
  baseUrl: import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_BASE_URL,
  apiKey: null,
  writesAuthenticated: false,
};

export function configureClient(next: Partial<ClientConfig>): void {
  config = { ...config, ...next };
}

export function getClientConfig(): Readonly<ClientConfig> {
  return config;
}

// --- errors ----------------------------------------------------------------

/** A refusal the backend described. `reason` is its stable machine-readable code. */
export class ApiError extends Error {
  readonly status: number;
  readonly reason: string | null;
  readonly entity: string | null;

  constructor(
    status: number,
    message: string,
    reason: string | null = null,
    entity: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.reason = reason;
    this.entity = entity;
  }
}

/** 401: the key is missing, wrong, or the backend now requires one. */
export class UnauthorizedError extends ApiError {
  constructor(message: string) {
    super(401, message);
    this.name = "UnauthorizedError";
  }
}

/** 429: the backend's rate limit was hit. */
export class RateLimitedError extends ApiError {
  constructor(message: string) {
    super(429, message);
    this.name = "RateLimitedError";
  }
}

/** The request was never sent: the backend requires a key and none is configured. */
export class MissingApiKeyError extends Error {
  constructor() {
    super(
      "This backend requires an API key for changes. Enter it in the Connection panel first.",
    );
    this.name = "MissingApiKeyError";
  }
}

/** The request never reached (or never got an answer from) the backend. */
export class NetworkError extends Error {
  constructor(baseUrl: string, cause: unknown) {
    super(
      `Could not reach the backend at ${baseUrl}. Is it running, and does its CORS_ORIGINS include this page's origin?`,
    );
    this.name = "NetworkError";
    this.cause = cause;
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof UnauthorizedError;
}

export function isRateLimited(error: unknown): boolean {
  return error instanceof RateLimitedError;
}

export function isMissingApiKey(error: unknown): boolean {
  return error instanceof MissingApiKeyError;
}

/** A short, human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

// --- transport -------------------------------------------------------------

type AuthMode = "required" | "optional";

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  auth?: AuthMode;
  signal?: AbortSignal;
}

/** 422 bodies carry a list of field errors; flatten them into one sentence. */
function describeValidationDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === "object") {
        const entry = item as { loc?: unknown[]; msg?: string };
        const where = Array.isArray(entry.loc)
          ? entry.loc.filter((segment) => segment !== "body").join(".")
          : "";
        return where ? `${where}: ${entry.msg ?? "invalid"}` : (entry.msg ?? "invalid");
      }
      return String(item);
    });
    return parts.join("; ");
  }
  return "The request was rejected.";
}

async function throwForResponse(response: Response): Promise<never> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const body = (payload ?? {}) as Record<string, unknown>;
  const message =
    typeof body.detail === "string"
      ? body.detail
      : describeValidationDetail(body.detail);
  const reason = typeof body.reason === "string" ? body.reason : null;
  const entity = typeof body.entity === "string" ? body.entity : null;

  if (response.status === 401) {
    throw new UnauthorizedError(
      `${message} Check the API key in the Connection panel.`,
    );
  }
  if (response.status === 429) {
    throw new RateLimitedError(
      `${message}. Slow the polling interval down or wait a minute.`,
    );
  }
  throw new ApiError(response.status, message, reason, entity);
}

async function request<T>(
  path: string,
  { method = "GET", body, auth = "optional", signal }: RequestOptions = {},
): Promise<T> {
  const needsKey = auth === "required";
  if (needsKey && config.writesAuthenticated && !config.apiKey) {
    // Never form the request: this is the frontend half of the auth gate.
    throw new MissingApiKeyError();
  }

  const headers: Record<string, string> = { Accept: "application/json" };
  const key = config.apiKey?.trim();
  if (key) headers[API_KEY_HEADER] = key;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${config.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new NetworkError(config.baseUrl, cause);
  }

  if (!response.ok) await throwForResponse(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const get = <T>(path: string, signal?: AbortSignal): Promise<T> =>
  request<T>(path, signal ? { signal } : {});

const post = <T>(
  path: string,
  body: unknown | undefined,
  signal?: AbortSignal,
): Promise<T> =>
  request<T>(path, {
    method: "POST",
    body,
    auth: "required",
    ...(signal ? { signal } : {}),
  });

// --- read-only endpoints (open, rate-limited) ------------------------------

export const getHealth = (signal?: AbortSignal) =>
  get<HealthResponse>("/health", signal);

export const getDemand = (signal?: AbortSignal) => get<Demand>("/demand", signal);

export const getShipments = (signal?: AbortSignal) =>
  get<Shipment[]>("/shipments", signal);

export const getRoutes = (signal?: AbortSignal) => get<Route[]>("/routes", signal);

export const getInventory = (signal?: AbortSignal) =>
  get<InventoryOverview>("/inventory", signal);

export const getVendors = (signal?: AbortSignal) =>
  get<Vendor[]>("/vendors", signal);

export const getAdminState = (signal?: AbortSignal) =>
  get<AdminState>("/admin/state", signal);

export const getAgentTools = (signal?: AbortSignal) =>
  get<ToolSpec[]>("/agent/tools", signal);

/**
 * The audit trail. Read-only, but the backend gates it, so the key is attached
 * when one is configured and a 401 is surfaced like any other.
 */
export const getAuditTrail = (
  { actionType, actor, limit = 50 }: { actionType?: string; actor?: string; limit?: number } = {},
  signal?: AbortSignal,
) => {
  const query = new URLSearchParams();
  if (actionType) query.set("action_type", actionType);
  if (actor) query.set("actor", actor);
  query.set("limit", String(limit));
  return get<AuditEntry[]>(`/audit?${query.toString()}`, signal);
};

// --- state-changing endpoints (authenticated) ------------------------------

/** Run one agent recovery pass. Mutates inventory, so it needs the key. */
export const runAgent = (maxReplans?: number, signal?: AbortSignal) =>
  post<AgentRun>(
    "/agent/recover",
    maxReplans === undefined ? undefined : { max_replans: maxReplans },
    signal,
  );

export const simulateShipmentDelay = (
  shipmentId: number,
  delayHours: number,
  signal?: AbortSignal,
) =>
  post<ShipmentDelayResponse>(
    "/simulate/shipment-delay",
    { shipment_id: shipmentId, delay_hours: delayHours },
    signal,
  );

export const simulateVendorFailure = (vendorId: number, signal?: AbortSignal) =>
  post<VendorFailureResponse>("/simulate/vendor-failure", { vendor_id: vendorId }, signal);

export const simulateRouteBlock = (routeId: number, signal?: AbortSignal) =>
  post<RouteBlockResponse>("/simulate/route-block", { route_id: routeId }, signal);

export const simulateDemandSpike = (
  dealerId: number,
  newRequiredQuantity: number,
  signal?: AbortSignal,
) =>
  post<DemandSpikeResponse>(
    "/simulate/demand-spike",
    { dealer_id: dealerId, new_required_quantity: newRequiredQuantity },
    signal,
  );

/** Restore the seeded scenario. Destructive, so it needs the key. */
export const resetScenario = (signal?: AbortSignal) =>
  post<unknown>("/admin/reset", undefined, signal);
