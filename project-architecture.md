# Project Architecture

**Agri Smart Supply-Chain Recovery Agent** — how the system is put together, and why each piece
sits where it does.

Companion docs: [problem & solution brief](problem-and-solution-brief.md) ·
[demo video script](demo-video-script.md) · [backend README](supply-chain-agent-backend/README.md)

---

## 1. The big picture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  frontend/  — React operator console (Vite + TypeScript)                │
│  live status · disruption buttons · reasoning trace in plain language   │
└───────────────┬─────────────────────────────────────────────────────────┘
                │  HTTP + X-API-Key (writes) · polling, no websockets
┌───────────────▼─────────────────────────────────────────────────────────┐
│  supply-chain-agent-backend/  — FastAPI                                 │
│                                                                         │
│  routers/    HTTP layer: CRUD, read views, actions, simulate, agent     │
│  services/   validation · transactions · audit   ← the ONLY mutator     │
│  agent/      tools → loop → trace → grounded explanation                │
│  optimizer.py  pure ranking: candidates → feasibility → weighted score  │
│  db/         SQLAlchemy models + the resettable seed scenario           │
└─────────────────────────────────────────────────────────────────────────┘
```

**The one rule that shapes everything:** the LLM must never be the source of a number, a decision
or a safety property. Each of those lives in exactly one testable place:

| Concern | Lives in | Why there |
|---|---|---|
| Cost / delivery / carbon arithmetic | `app/optimizer.py` — pure, no DB, no clock | Deterministic and unit-testable; same input always ranks the same way |
| Whether an action is *allowed* | `app/services/action_service.py` | One validator for every caller, human or agent |
| What the agent does, in order | `app/agent/loop.py` | Policy and caps must be provable code, not model judgement |
| What the agent *says* | `app/agent/explain.py` | The only place a model may write prose — and its output is checked before it is shown |

---

## 2. Data model

Seven tables; SQLite by default so there is nothing to install.

| Model | Key fields |
|---|---|
| `Product` | id, name, unit |
| `Supplier` | price/unit, available_quantity, delivery_hours, carbon_per_unit, is_available |
| `Warehouse` | location, inventory (`product_id → quantity`) |
| `Dealer` | required_quantity, deadline, current_inventory |
| `Route` | from/to location, distance_km, travel_time_hours, carbon_per_km, is_available |
| `Shipment` | product, from/to, quantity, status (`PENDING → IN_TRANSIT → DELAYED/ARRIVED/CANCELLED`), expected_arrival, delay_hours |
| `AuditLog` | timestamp, actor (`agent`/`system`), action_type, details (before/after JSON), result |

Locations share one integer namespace so a route can start anywhere: suppliers **1–99**,
warehouses **101–199**, dealers **201–299**. The ranges are disjoint, so an endpoint id resolves
to exactly one entity without a `location_type` column.

**Seeded scenario** (restored by one `POST /admin/reset`, timestamps relative to seed time so it
is always "live"): dealer **Krishi Seva Kendra (Indore)** needs **1,000 bags of urea in 72 h**,
holds 300; a 700-bag shipment is en route from Central Depot; 3 vendors with deliberately
different price/speed/carbon trade-offs; 3 warehouses (450 / 120 / 600 bags); 4 routes.

---

## 3. Request flows

### 3.1 A read (the console's status polling)

```text
React (hooks.ts, 4 s poll, pauses when tab hidden)
  → client.ts  (the only fetch module; attaches X-API-Key when required)
    → routers/inventory.py → services/inventory_service.py → SQLAlchemy → SQLite
      ← computed view JSON (totals, shortfalls, constraint status are derived, never stored)
```

Read models (`/inventory`, `/vendors`, `/demand`) are **GET-only views** with every derived field
computed by the backend — the console does no domain arithmetic of its own, so UI and data cannot
disagree.

### 3.2 A state change (human or agent — same path)

```text
caller → POST /vendor/3/purchase  (X-API-Key required, rate-limited)
  → security.py     constant-time key check BEFORE body validation
  → ratelimit.py    429 {"reason": "rate_limited"} when over the cap
  → action_service.py
       1. validate against CURRENT database state (not what the caller claims)
       2. infeasible? → 409 + machine-readable reason, NOTHING written
       3. feasible?   → change + AuditLog entry commit in ONE transaction
       4. return the resulting state, with before/after values
```

Every mutating endpoint goes through this one service. The agent's tools wrap these same
endpoints, so the agent inherits exactly the validation a human caller gets — there is no side door.

### 3.3 A disruption (demo trigger)

`POST /simulate/shipment-delay | vendor-failure | route-block | demand-spike` — behaves like any
action (validated, atomic, audited) but writes `action_type: "disruption_injected"`, so a demo's
whole timeline can be replayed from the audit trail alone.

---

## 4. The optimizer (the decision core)

`POST /optimize/recovery { shortage_quantity, deadline }`. The router-side service snapshots the
DB into a `RecoveryState`; the optimizer itself is a **pure function** — no DB, no clock, no LLM.

1. **Candidates** — every warehouse transfer and vendor purchase, each sized to exactly the
   shortage. Transfers add road cost (`30/km` on the fastest open route) so they compare fairly
   with a vendor's delivery-inclusive price.
2. **Feasibility** — enough stock (`available ≥ shortage`) **and** on time
   (`delivery_hours ≤ deadline − now`) **and** an open route. Everything dropped is returned with
   a stable reason: `insufficient_quantity`, `misses_deadline`, `no_available_route`.
3. **Scoring** — min-max normalise each metric across feasible candidates, then weight:
   `score = 0.4·cost + 0.4·delivery + 0.2·carbon` (lower is better, `0` is perfect).
4. **Determinism** — ties break on cost → delivery → carbon → name → id. The same state always
   produces the same ranking; dictionary order can never leak in.

For the seeded 700-bag shortfall this ranks **vendor 3, Bharat Urea Traders: ₹255,500 / 12 h /
2,940 kg CO₂ / score 0.00** first, and explains why each of the other four candidates was excluded.

---

## 5. The agent layer

Ten tools, each a thin wrapper over a real endpoint (catalogue published at `GET /agent/tools`):
five reads (`get_demand`, `get_inventory`, `get_vendors`, `get_shipments`, `get_routes`),
`optimize_recovery`, `verify_state`, and the three mutators (`transfer_inventory`,
`purchase_from_vendor`, `reroute_shipment`).

**The loop** (`app/agent/loop.py`) — the step order is code, not model discretion:

```text
observe → detect ──(no violation)──→ stop: no_action_needed
   │ violation
investigate → optimize → decide → execute → verify ──(covered)──→ resolved
   ▲                                        │
   └───────── replan (max 5) ◄──────── not covered / refused
```

**Five guardrails, each a code path with tests:**

1. **Grounding** — every number in the final prose is extracted and checked against the trace;
   an untraceable figure discards the answer, one regeneration is allowed, then a deterministic
   template (grounded by construction) takes over.
2. **No silent action** — a decision must match the optimizer's top-ranked option (tool, target,
   quantity) from the same cycle, or nothing runs.
3. **Refuse if uncertain** — zero feasible options ends the run honestly; no choice can be forced.
4. **Bounded autonomy** — ≤ 5 replan cycles, ≤ 15 tool calls per cycle; refused actions are never retried.
5. **Structured output only** — decisions are validated JSON against an `ActionDecision` schema;
   prose is never parsed for actions.

**The LLM is optional.** With `GROQ_API_KEY` set, a Groq model writes the closing explanation —
subject to guardrail 1. Unset, a template writes it and the whole system (all 264 tests included)
runs offline.

---

## 6. The console (frontend)

```
src/api/client.ts    the ONLY fetch module; refuses to send an unauthenticated write
src/api/hooks.ts     polling (tick scheduled after the previous completes; pauses when hidden)
src/lib/describe.ts  trace JSON → plain-language sentences, read from each step's own result
src/state/useAgentRun.ts   run lifecycle + progressive step reveal (~320 ms apart, skippable)
src/components/      one component per panel: status, disruptions, agent feed, before/after, outcome
```

Design decisions worth knowing:

- **Polling, not websockets** — the backend has no streaming endpoint; each poll tick is scheduled
  *after* the previous finishes so requests never pile up, and pauses when the tab is hidden.
- **Auth is structural** — mutating calls declare `auth: "required"`, and `client.ts` refuses to
  form the request unless a key is configured or the backend reports writes are open. A component
  *cannot forget* the auth layer. The key lives in `localStorage`, never in the bundle.
- **Grounded UI** — the console reads sentences out of each step's recorded result, mirroring the
  backend's grounding rule, and shows the raw JSON behind every claim behind a *view tool call* toggle.

---

## 7. Cross-cutting: security & reliability

| Layer | Mechanism |
|---|---|
| Auth | `X-API-Key` on all 34 state-changing operations + the audit trail; constant-time compare; checked before body parsing; unset key only allowed in development/test |
| Rate limiting | 200/min default; **10/min** on the agent trigger (each call can spend money); 60/min on the optimizer; `429` with a machine-readable reason |
| Validation | Typed Pydantic schemas with explicit bounds on every request/response; `404` with context, `409 + reason` for conflicts, `422` for malformed bodies |
| Atomicity | Change + audit entry commit together; a refused action leaves no trace |
| Agent least privilege | No DB, shell or HTTP client for the LLM — the ten tools are its entire surface; no tool deletes or resets anything |
| Config | All settings from environment (`.env.example` documents every name); no secret in the repo; wildcard CORS rejected at startup |

**Verification:** 264 offline tests (seed contract, CRUD, actions + rollback, optimizer ranking,
agent outcomes and guardrails, security); `demo.py` = scripted scenario with 39 assertions;
`evaluate.py` = N-run randomized sweep with reproducible seeds and JSON output.

---

## 8. Repository layout

```
frontend/                          React operator console (Vite + TypeScript)
  src/api/                         client (the only fetch), types, polling hooks
  src/lib/                         describe / disruptions / supply / format / read
  src/state/                       useAgentRun — the run lifecycle
  src/components/                  one component per panel
supply-chain-agent-backend/
  app/
    main.py                        app wiring: lifespan, CORS, error mapping
    config.py                      pydantic-settings, environment-driven
    security.py  ratelimit.py      API-key auth · slowapi limiter
    optimizer.py                   the pure ranking function
    locations.py                   the location id namespace
    routers/                       HTTP endpoints (thin)
    services/                      validation, transactions, audit (the only mutator)
    schemas/                       Pydantic request/response models
    models/  db/                   SQLAlchemy models · session · seed scenario
    agent/                         tools · loop · trace · decision · explain · constants
  tests/                           264 offline tests
  demo.py  evaluate.py             scripted single run · N-run evaluation sweep
problem-and-solution-brief.md      the problem statement and the solution approach
project-architecture.md            this document
demo-video-script.md               shot-by-shot script for the 3–5 minute demo video
```

*See also: [backend README](supply-chain-agent-backend/README.md) for the full API reference and
seed state · [SECURITY.md](supply-chain-agent-backend/SECURITY.md) for each measure's reasoning ·
[EVALUATION.md](supply-chain-agent-backend/EVALUATION.md) for measured results.*
