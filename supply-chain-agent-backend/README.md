# supply-chain-agent-backend

FastAPI backend for the supply chain agent: entities and validation, a
resettable seed scenario, CRUD and read-only views, transaction-safe
state-changing actions, scripted disruption triggers for demos, a deterministic
recovery optimizer, and an agent layer that orchestrates those tools and
explains what it did.

SQLite + SQLAlchemy by default, so there is no external database to install or
run.

**Companion documents**

| Document | What is in it |
| --- | --- |
| [PRESENTATION.md](PRESENTATION.md) | Approach, the final solution, the challenges faced, and the demo video script |
| [EVALUATION.md](EVALUATION.md) | How recovery was measured over N runs, and what the logged results actually show |
| [SECURITY.md](SECURITY.md) | Every security measure and the reasoning behind it |

**Jump to:** [architecture](#project-structure) · [endpoints](#endpoints) ·
[agent tools](#tools) · [security](#security) · [demo script](#demo--verification-script) ·
[evaluation](#evaluation-summary) · [configuration](#configuration)

## Quickstart

```bash
cd supply-chain-agent-backend

python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash); use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

cp .env.example .env               # optional: tweak settings
uvicorn app.main:app --reload
```

* API docs: <http://127.0.0.1:8000/docs>
* Reset to the starting state: `curl -X POST http://127.0.0.1:8000/admin/reset`
* Health: `curl http://127.0.0.1:8000/health`

With no `API_KEY` set the app runs in development demo mode and writes are open;
set `API_KEY` and send it as `X-API-Key` to require authentication on every
state-changing endpoint (see [Security](#security)).

On first start the app creates `supply_chain.db` and, when it is empty, loads
the seed scenario automatically (`AUTO_SEED=true`).

You can also seed from the command line — same code path as the endpoint:

```bash
python -m app.db.seed
```

### Operator console

There is a React console in `../frontend` that polls this API for live status,
drives the `/simulate/*` triggers, runs the agent and renders its reasoning trace
in plain language. Its dev server is pinned to `localhost:5173`, which is exactly
the default `CORS_ORIGINS` here, so the two work together with no configuration.
It requires `API_KEY` to be set before its controls will call anything that
changes state.

## Project structure

```
app/
  main.py            FastAPI app: lifespan, error handlers, CORS, router wiring
  config.py          Settings loaded from environment variables (pydantic-settings)
  security.py        API-key auth (require_api_key) + WRITE_GUARD for mutating routes
  ratelimit.py       the slowapi limiter, its middleware and its 429 handler
  utils.py           naive-UTC helpers (utcnow, hours_from_now)
  db/
    base.py          Declarative Base + create_all/drop_all
    session.py       engine, SessionLocal, get_db dependency
    seed.py          the seed scenario + full reset (CLI + API entry point)
  locations.py       canonical location id namespace + LocationKind
  optimizer.py       pure recovery optimizer: no DB, no clock, deterministic
  agent/             the agent layer: trace.py (reasoning trace),
                     tools.py (thin tool wrappers), loop.py (the loop),
                     explain.py (grounded explanation), constants.py
  models/            SQLAlchemy models: product, supplier, warehouse, dealer,
                     route, shipment, audit_log
  schemas/           Pydantic request/response schemas, one module per entity
  services/          all DB access; routers stay thin. base.CRUDService is reused;
                     action_service.py owns the validated, atomic state changes
                     (transfer / reroute / purchase / cancel);
                     optimizer_service.py snapshots the DB into the optimizer
  routers/           products, suppliers, warehouses, dealers, routes,
                     shipments, audit_logs, admin, the read-only views
                     (inventory, vendors, demand), the action endpoints
                     (actions.py), the disruption triggers (simulate.py), the
                     recovery optimizer (optimize.py), the audit view (audit.py)
                     and deps.py (DI providers)
tests/               seed-state, CRUD/validation, actions, simulate, optimizer,
                     agent and security tests
SECURITY.md          the security measures and the reasoning behind each
```

Layer direction: `routers → services → models/schemas`. Routers never build
queries and services never raise HTTP errors: they raise `NotFoundError` for a
missing row and `ConflictError` for an infeasible action, which `main.py` maps to
`404` and `409` respectively.

## Data models

| Model | Fields |
|---|---|
| `Product` | `id`, `name`, `unit` |
| `Supplier` | `id`, `name`, `product_id`, `price_per_unit`, `available_quantity`, `delivery_hours`, `carbon_per_unit`, `is_available` |
| `Warehouse` | `id`, `name`, `location`, `inventory` (JSON `product_id -> quantity`) |
| `Dealer` | `id`, `name`, `location`, `required_quantity`, `deadline`, `current_inventory` |
| `Route` | `id`, `from_location_id`, `to_location_id`, `distance_km`, `travel_time_hours`, `carbon_per_km`, `is_available` |
| `Shipment` | `id`, `product_id`, `from_id`, `to_id`, `quantity`, `status`, `expected_arrival`, `actual_arrival`, `delay_hours` |
| `AuditLog` | `id`, `timestamp`, `actor`, `action_type`, `details` (JSON), `result` |

`Shipment.status` is one of `PENDING`, `IN_TRANSIT`, `DELAYED`, `ARRIVED`,
`CANCELLED` — the last added by the cancel action, and additive to the Step 1
enum. `ARRIVED` and `CANCELLED` are terminal: such a shipment can no longer be
rerouted or cancelled, and it no longer counts as inbound supply.
`AuditLog.actor` is `agent` or `system`.

Read schemas expose a couple of derived values that are useful later:
`Dealer.shortfall` (`required_quantity - current_inventory`) and
`Route.carbon_emission` (`distance_km * carbon_per_km`). These are computed, not
stored, so the stored columns match the specification exactly.

### Location ids

`Route` and `Shipment` reference locations as plain integers (a route can start
at a supplier, a warehouse or a dealer), so one shared namespace is used:

| Location kind | Id range | Seeded ids |
|---|---|---|
| Supplier | 1 – 99 | 1, 2, 3 |
| Warehouse | 101 – 199 | 101, 102, 103 |
| Dealer | 201 – 299 | 201 |

The ranges are disjoint, so an endpoint id always resolves to exactly one
entity without an extra `location_type` column.

## Seeded starting state

`POST /admin/reset` drops every table, recreates the schema and writes exactly
this scenario (also what `python -m app.db.seed` does):

* **Product** — `Urea`, unit `bag`.
* **Suppliers** (3, deliberately different trade-offs):

  | id | name | price/unit | qty | delivery | carbon/unit |
  |---|---|---|---|---|---|
  | 1 | AgroChem Industries | 24.90 (cheapest) | 800 | 30 h (slowest) | 6.5 (dirtiest) |
  | 2 | GreenFields Fertilizers | 26.75 | 500 | 8 h (fastest) | 2.8 (greenest) |
  | 3 | Bharat Urea Traders | 28.50 (priciest) | 1200 | 12 h | 4.2 |

* **Warehouses** (3, different stock): Central Depot / Nagpur = 450 bags,
  North Hub / Ludhiana = 120 bags, East Yard / Kolkata = 600 bags.
* **Dealer** — Krishi Seva Kendra / Indore, requires 1,000 bags, holds 300
  (shortfall 700), deadline = seed time + 72 h.
* **Shipment** — 1 × 700 bags, `PENDING`, Central Depot (101) → dealer (201),
  expected to arrive 24 h after seeding, i.e. well before the deadline.
* **Routes** (4, all `is_available`): Central Depot→dealer (480 km / 9.5 h),
  North Hub→dealer (1150 km / 22 h), East Yard→dealer (1450 km / 27 h),
  GreenFields→dealer (620 km / 11 h).
* **AuditLog** — one `system` / `database_reset` entry recording the seeded
  timestamps and the shortfall.

Deadline and ETA are stored as timestamps relative to the moment of seeding, so
the scenario is always "live" and resetting at any time restores the exact same
situation.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/admin/reset` | Reset the DB to the seeded starting state |
| GET | `/admin/state` | Counts per table + per-warehouse inventory |
| GET/POST | `/products` | List / create products |
| GET/PATCH/DELETE | `/products/{id}` | Read / update / delete a product |
| GET/POST | `/suppliers` | List (`?only_available=true`, `?product_id=`) / create |
| GET/PATCH/DELETE | `/suppliers/{id}` | Read / update / delete a supplier |
| GET/POST | `/warehouses` | List / create warehouses |
| GET/PATCH/DELETE | `/warehouses/{id}` | Read / update / delete a warehouse |
| GET/PUT | `/warehouses/{id}/inventory/{product_id}` | Read / overwrite one stock level |
| GET/POST | `/dealers` | List / create dealers |
| GET/PATCH/DELETE | `/dealers/{id}` | Read / update / delete a dealer |
| GET/POST | `/routes` | List (`?only_available=true`, `?to_location_id=`) / create |
| GET/PATCH/DELETE | `/routes/{id}` | Read / update / delete a route |
| GET/POST | `/shipments` | List (`?status=`, `?to_id=`) / create |
| GET/PATCH/DELETE | `/shipments/{id}` | Read / update / delete a shipment |
| PATCH | `/shipments/{id}/status` | Transition status; stamps `actual_arrival` and computes `delay_hours` on `ARRIVED` |
| GET/POST | `/audit-logs` | List (`?actor=`) / append (append-only: no update or delete routes) |
| GET | `/audit-logs/recent` | Newest entries first |
| GET | `/audit-logs/{id}` | Read one entry |
| GET | `/inventory` | Current stock for every warehouse and the dealer |
| GET | `/inventory/{location_id}` | Stock for one location (warehouse 101-199, dealer 201-299) |
| GET | `/vendors` | Suppliers as comparison-ready vendors (`?only_available=`, `?product_id=`) |
| GET | `/vendors/{id}` | One vendor with its product context |
| GET | `/demand` | Dealer requirement, stock, deadline, shortage and constraint status (`?dealer_id=`) |
| POST | `/inventory/transfer` | Move stock between locations (validated, atomic) |
| POST | `/shipment/{id}/reroute` | Put a shipment on a different available route |
| POST | `/vendor/{id}/purchase` | Reserve vendor stock and create an inbound shipment |
| POST | `/shipment/{id}/cancel` | Cancel a shipment that has not landed |
| POST | `/simulate/shipment-delay` | Delay a shipment (demo trigger) |
| POST | `/simulate/vendor-failure` | Fail a vendor (demo trigger) |
| POST | `/simulate/route-block` | Block a route (demo trigger) |
| POST | `/simulate/demand-spike` | Raise dealer demand (demo trigger) |
| POST | `/optimize/recovery` | Rank recovery options for a shortage (deterministic) |
| GET | `/agent/tools` | List the agent's tools and the endpoints they wrap |
| POST | `/agent/recover` | Run one recovery pass; returns the explanation + reasoning trace |
| GET | `/audit` | The audit trail, newest first (`?actor=`, `?action_type=`) — **requires the API key** |

Endpoints marked below as writes require the `X-API-Key` header; reads are open
but rate-limited. List endpoints accept `skip` and `limit` (max 500). Every
request and response body is validated by a Pydantic schema with explicit numeric
bounds; invalid payloads return `422`, unknown ids return `404`, and constraint
conflicts (e.g. a duplicate product name) return `409`. The action endpoints
reuse that `409` for infeasible requests and add a stable, machine-readable
`reason` (see below). A request over the configured rate limit returns `429`.

## Read-only views

These are the read models the agent and the UI consume: **GET-only** (plus
`POST /optimize/recovery`, which computes and mutates nothing), and every
response — including the computed fields — is a Pydantic model declared with
`response_model`, so the OpenAPI schema at `/docs` is the contract. They share
the location id namespace (suppliers 1-99, warehouses 101-199, dealers 201-299).

One read is deliberately *not* open: `GET /audit` requires the API key, because
the trail records every mutation with its before/after state. It returns entries
newest first and filters on `actor` and `action_type`:

```bash
curl 'localhost:8000/audit?action_type=disruption_injected&limit=5' \
  -H 'X-API-Key: your-key'
```

```json
[
  {
    "actor": "system",
    "action_type": "disruption_injected",
    "details": {
      "disruption": "route_block",
      "route_id": 1,
      "from_location_id": 101,
      "to_location_id": 201,
      "is_available": {"before": true, "after": false}
    },
    "result": "success",
    "id": 2,
    "timestamp": "2026-09-13T11:18:39.199907"
  }
]
```

### GET /inventory

Stock for every warehouse plus every dealer, with a per-location and grand
total. Warehouses report a `product_id -> quantity` map; a dealer reports its
single `current_inventory`, which is not tied to a product in the schema.

```json
{
  "generated_at": "2026-09-13T10:03:12.420032",
  "warehouses": [
    {"location_id": 101, "name": "Central Depot", "location": "Nagpur", "location_type": "warehouse", "inventory": {"1": 450}, "total_quantity": 450},
    {"location_id": 102, "name": "North Hub", "location": "Ludhiana", "location_type": "warehouse", "inventory": {"1": 120}, "total_quantity": 120},
    {"location_id": 103, "name": "East Yard", "location": "Kolkata", "location_type": "warehouse", "inventory": {"1": 600}, "total_quantity": 600}
  ],
  "dealers": [
    {"location_id": 201, "name": "Krishi Seva Kendra", "location": "Indore", "location_type": "dealer", "current_inventory": 300, "total_quantity": 300}
  ],
  "total_quantity": 1470
}
```

`total_quantity` is computed (`sum(inventory.values())`, or the dealer's own
number) and `location_type` discriminates the two shapes.

### GET /inventory/{location_id}

One location, resolved through the id namespace. Warehouses and dealers return
the same shapes as above (just a single object):

```json
{
  "location_id": 101,
  "name": "Central Depot",
  "location": "Nagpur",
  "location_type": "warehouse",
  "inventory": {"1": 450},
  "total_quantity": 450
}
```

```json
{
  "location_id": 201,
  "name": "Krishi Seva Kendra",
  "location": "Indore",
  "location_type": "dealer",
  "current_inventory": 300,
  "total_quantity": 300
}
```

Supplier ids are locations in the shipping graph but hold no inventory, so they
return `404` pointing at the vendor view; ids outside every range return `404`
with the namespace spelled out:

```json
{
  "detail": "Location 1 is a supplier, which holds no inventory; supplier availability is at /vendors/1",
  "entity": "Location",
  "id": 1
}
```

### GET /vendors and GET /vendors/{id}

Suppliers of every product, ordered by `price_per_unit` (cheapest first), each
enriched with its product's name and unit — everything needed to compare offers
on price, availability, delivery time and carbon. `only_available=true` drops
vendors flagged unavailable; `product_id=` narrows to one product. This is the
read *view*; `/suppliers` remains the CRUD resource.

```json
[
  {
    "id": 1,
    "name": "AgroChem Industries",
    "product_id": 1,
    "product_name": "Urea",
    "unit": "bag",
    "price_per_unit": 24.9,
    "available_quantity": 800,
    "delivery_hours": 30.0,
    "carbon_per_unit": 6.5,
    "is_available": true
  },
  {
    "id": 2,
    "name": "GreenFields Fertilizers",
    "product_id": 1,
    "product_name": "Urea",
    "unit": "bag",
    "price_per_unit": 26.75,
    "available_quantity": 500,
    "delivery_hours": 8.0,
    "carbon_per_unit": 2.8,
    "is_available": true
  }
]
```

`GET /vendors/1` returns the same object for a single vendor, or `404` for an
unknown id.

### GET /shipments and GET /shipments/{id}

Every shipment with its status, or one shipment's detail. These two already
existed from the data layer and are unchanged: `?status=` and `?to_id=` filter
the list.

```json
[
  {
    "product_id": 1,
    "from_id": 101,
    "to_id": 201,
    "quantity": 700,
    "status": "PENDING",
    "expected_arrival": "2026-09-14T10:03:39.044396",
    "actual_arrival": null,
    "delay_hours": 0.0,
    "id": 1
  }
]
```

### GET /routes

Every route with its availability (also unchanged from the data layer, with
`?only_available=` and `?to_location_id=` filters). `carbon_emission` is
computed as `distance_km * carbon_per_km`.

```json
[
  {
    "from_location_id": 101,
    "to_location_id": 201,
    "distance_km": 480.0,
    "travel_time_hours": 9.5,
    "carbon_per_km": 0.12,
    "is_available": true,
    "id": 1,
    "carbon_emission": 57.6
  }
]
```

### GET /demand

What the dealer needs, what it has, and whether that is feasible. `dealer_id=`
selects a dealer; without it the lowest-id dealer is used (the seed has one).

```json
{
  "dealer_id": 201,
  "dealer_name": "Krishi Seva Kendra",
  "location": "Indore",
  "required_quantity": 1000,
  "available_quantity": 300,
  "deadline": "2026-09-16T10:03:12.382060",
  "active_shipments": [
    {
      "product_id": 1,
      "from_id": 101,
      "to_id": 201,
      "quantity": 700,
      "status": "PENDING",
      "expected_arrival": "2026-09-14T10:03:12.382067",
      "actual_arrival": null,
      "delay_hours": 0.0,
      "id": 1
    }
  ],
  "shortage": 700,
  "active_shipment_quantity": 700,
  "constraint_violations": ["shortage of 700 units (300 of 1000 on hand)"],
  "constraint_violated": true
}
```

Four fields are computed, so the payload can never contradict itself:

| Field | Rule |
|---|---|
| `shortage` | `max(required_quantity - available_quantity, 0)` |
| `active_shipment_quantity` | sum of the quantities of `active_shipments` |
| `constraint_violations` | one entry per breach (see below) |
| `constraint_violated` | `true` when `shortage > 0`, or when any active shipment's `expected_arrival` is after `deadline` |

`available_quantity` is the dealer's stock on hand (`current_inventory`); stock
that is still in transit is deliberately *not* counted as available, it is
reported in `active_shipments` and `active_shipment_quantity` instead. An
*active* shipment is one inbound to the dealer (`to_id == dealer_id`) whose
status is neither `ARRIVED` nor `CANCELLED`. A shipment with no
`expected_arrival` is not treated as late.

In the seeded state the shipment lands well inside the 72-hour window, so the
only violation is the 700-bag shortage. Pushing the deadline before the ETA
adds the second kind:

```json
{
  "shortage": 0,
  "constraint_violations": ["shipment 1 is expected 25.0 h after the deadline"],
  "constraint_violated": true
}
```

## State-changing actions

These are the only endpoints that mutate the supply chain. Each is a thin
wrapper over `app.services.action_service.ActionService`, the single place this
validation lives, and each one:

1. validates the request against the **current database state**, never against
   what the caller claims that state is;
2. refuses an infeasible action with `409` (and writes nothing);
3. applies the change and its `AuditLog` entry in **one transaction**, so an
   accepted action can never land without its audit record and a refused one
   leaves no trace;
4. returns the **resulting state** — including before/after where a row changed
   — never just a success flag.

The agent layer must call these service methods rather than writing rows
directly, so this validation cannot be bypassed from the caller side.

A refused action answers with a human-readable `detail` and a stable `reason`
the caller can branch on:

```json
{
  "detail": "Warehouse 103 holds 600 of product 1; cannot transfer 601",
  "reason": "insufficient_stock"
}
```

| `reason` | Endpoint | Meaning |
|---|---|---|
| `same_location` | transfer | source and destination are the same location |
| `invalid_source_location` | transfer | `from_warehouse_id` is not a warehouse (101-199) |
| `not_a_stock_location` | transfer | destination is a supplier or outside the namespace |
| `insufficient_stock` | transfer | source holds less than the requested quantity |
| `ambiguous_product` | transfer | `product_id` omitted while several products exist |
| `no_product` | transfer | the catalogue is empty |
| `shipment_not_reroutable` | reroute | shipment already `ARRIVED` or `CANCELLED` |
| `route_unavailable` | reroute | the route is flagged unavailable |
| `route_destination_mismatch` | reroute | the route ends somewhere other than the shipment's destination |
| `vendor_unavailable` | purchase | the supplier is flagged unavailable |
| `insufficient_supplier_stock` | purchase | the vendor holds less than the requested quantity |
| `shipment_already_arrived` | cancel | the shipment already landed |
| `shipment_already_cancelled` | cancel | the shipment is already cancelled |

Unknown ids are still `404` (an in-range warehouse that does not exist, a missing
shipment/route/vendor), and a malformed body is still `422`.

### POST /inventory/transfer

`{ from_warehouse_id, to_id, quantity, product_id? }` moves stock out of a
warehouse and into another warehouse or the dealer. `product_id` may be omitted
while the catalogue holds exactly one product (it is required otherwise), so the
seeded scenario works with the three-field body from the specification. The
source must be a warehouse (101-199) and must hold enough stock; the destination
must be a warehouse or the dealer. Only the destination's shape varies —
warehouses report a `product_id -> quantity` map, the dealer its single number,
exactly as `/inventory` does.

```json
{
  "product_id": 1,
  "quantity": 100,
  "source_before": {"location_id": 101, "name": "Central Depot", "location": "Nagpur", "location_type": "warehouse", "inventory": {"1": 450}, "total_quantity": 450},
  "source_after": {"location_id": 101, "name": "Central Depot", "location": "Nagpur", "location_type": "warehouse", "inventory": {"1": 350}, "total_quantity": 350},
  "destination_before": {"location_id": 201, "name": "Krishi Seva Kendra", "location": "Indore", "location_type": "dealer", "current_inventory": 300, "total_quantity": 300},
  "destination_after": {"location_id": 201, "name": "Krishi Seva Kendra", "location": "Indore", "location_type": "dealer", "current_inventory": 400, "total_quantity": 400},
  "audit_log_id": 2
}
```

### POST /shipment/{id}/reroute

`{ new_route_id }` puts a shipment on a different route. The route defines the
new path: the shipment's `from_id` becomes the route's origin and
`expected_arrival` is recomputed as *now + the route's travel time*. The
destination cannot change — a route ending anywhere other than the shipment's
`to_id` is refused with `route_destination_mismatch` — so a reroute can never
silently divert goods away from the location that is expecting them.

```json
{
  "shipment": {"product_id": 1, "from_id": 102, "to_id": 201, "quantity": 700, "status": "PENDING", "expected_arrival": "2026-09-14T08:32:10.652376", "actual_arrival": null, "delay_hours": 0.0, "id": 1},
  "route": {"from_location_id": 102, "to_location_id": 201, "distance_km": 1150.0, "travel_time_hours": 22.0, "carbon_per_km": 0.14, "is_available": true, "id": 2, "carbon_emission": 161.0},
  "previous_from_id": 101,
  "previous_to_id": 201,
  "previous_expected_arrival": "2026-09-14T10:32:10.615990",
  "audit_log_id": 2
}
```

### POST /vendor/{id}/purchase

`{ quantity }` buys stock from a supplier: the vendor's `available_quantity` is
decremented (so the same stock cannot be sold twice) and a new `PENDING`
shipment is created from the supplier to the (lowest-id, i.e. seeded) dealer,
scheduled to arrive after the vendor's `delivery_hours`.

```json
{
  "vendor": {"id": 1, "name": "AgroChem Industries", "product_id": 1, "product_name": "Urea", "unit": "bag", "price_per_unit": 24.9, "available_quantity": 600, "delivery_hours": 30.0, "carbon_per_unit": 6.5, "is_available": true},
  "vendor_available_before": 800,
  "shipment": {"product_id": 1, "from_id": 1, "to_id": 201, "quantity": 200, "status": "PENDING", "expected_arrival": "2026-09-14T16:32:10.673702", "actual_arrival": null, "delay_hours": 0.0, "id": 2},
  "audit_log_id": 2
}
```

### POST /shipment/{id}/cancel

Cancels a shipment that has not landed, setting its status to `CANCELLED`. The
row is kept, so its audit trail and history survive, but it stops counting as
inbound supply immediately: `/demand` no longer lists it and `?to_id=` no longer
returns it. Reserving vendor stock is *not* automatically returned.

```json
{
  "shipment": {"product_id": 1, "from_id": 101, "to_id": 201, "quantity": 700, "status": "CANCELLED", "expected_arrival": "2026-09-14T10:32:10.685165", "actual_arrival": null, "delay_hours": 0.0, "id": 1},
  "previous_status": "PENDING",
  "audit_log_id": 2
}
```

### Audit trail

Every action appends exactly one `AuditLog` row in the same transaction, with
the before and after state in `details`:

```json
{
  "id": 2,
  "timestamp": "2026-09-13T10:32:10.674000",
  "actor": "system",
  "action_type": "inventory_transfer",
  "details": {
    "product_id": 1,
    "quantity": 100,
    "from": {"location_id": 101, "location_type": "warehouse", "before": 450, "after": 350},
    "to": {"location_id": 201, "location_type": "dealer", "before": 300, "after": 400}
  },
  "result": "success"
}
```

The action types are `inventory_transfer`, `shipment_reroute`, `vendor_purchase`
and `shipment_cancel`. HTTP calls are recorded as `system`; the action service
accepts an `actor` keyword so the future agent layer can log the same
operations as `agent`.

The specification names two paths in the singular (`/shipment/{id}/...`,
`/vendor/{id}/purchase`); plural aliases (`/shipments/{id}/...`,
`/vendors/{id}/purchase`) are registered too and hidden from the OpenAPI schema.

## Disruption triggers

Four `POST /simulate/*` endpoints break the seeded scenario on purpose, for live
demos. They behave exactly like the actions above — validated against current
state, atomic, and returning the resulting state — and each appends one
`AuditLog` row with `action_type = "disruption_injected"` plus a
`details.disruption` kind, so the timeline of a demo can be replayed and
narrated from the audit trail alone.

| Endpoint | Body | Effect |
|---|---|---|
| `/simulate/shipment-delay` | `{ shipment_id, delay_hours }` | status → `DELAYED`, ETA pushed out by `delay_hours` (compounds on repeat) |
| `/simulate/vendor-failure` | `{ vendor_id }` | vendor `is_available` → false |
| `/simulate/route-block` | `{ route_id }` | route `is_available` → false |
| `/simulate/demand-spike` | `{ dealer_id, new_required_quantity }` | dealer requirement raised |

A trigger that is infeasible is refused with the same `409` + `reason` shape as
the actions, and changes nothing:

| `reason` | Endpoint | Meaning |
|---|---|---|
| `shipment_not_delayable` | shipment-delay | shipment already `ARRIVED` or `CANCELLED` |
| `vendor_already_unavailable` | vendor-failure | the vendor already failed |
| `route_already_unavailable` | route-block | the route is already blocked |
| `not_a_demand_spike` | demand-spike | `new_required_quantity` does not exceed the current requirement |

### POST /simulate/shipment-delay

Marks the shipment `DELAYED` and pushes `expected_arrival` by `delay_hours`.
The delay compounds: calling it again adds to the running `delay_hours` and
pushes the ETA from where it already was, so disruptions can be stacked. Once
the pushed ETA passes the dealer's deadline, `GET /demand` reports the
`constraint_violated` case documented above.

```json
{
  "shipment": {"product_id": 1, "from_id": 101, "to_id": 201, "quantity": 700, "status": "DELAYED", "expected_arrival": "2026-09-14T22:37:29.880696", "actual_arrival": null, "delay_hours": 12.0, "id": 1},
  "delay_hours": 12.0,
  "previous_status": "PENDING",
  "previous_expected_arrival": "2026-09-14T10:37:29.880696",
  "audit_log_id": 2
}
```

### POST /simulate/vendor-failure

```json
{
  "vendor": {"id": 2, "name": "GreenFields Fertilizers", "product_id": 1, "product_name": "Urea", "unit": "bag", "price_per_unit": 26.75, "available_quantity": 500, "delivery_hours": 8.0, "carbon_per_unit": 2.8, "is_available": false},
  "previous_is_available": true,
  "audit_log_id": 2
}
```

### POST /simulate/route-block

```json
{
  "route": {"from_location_id": 103, "to_location_id": 201, "distance_km": 1450.0, "travel_time_hours": 27.0, "carbon_per_km": 0.16, "is_available": false, "id": 3, "carbon_emission": 232.0},
  "previous_is_available": true,
  "audit_log_id": 2
}
```

### POST /simulate/demand-spike

```json
{
  "dealer": {"name": "Krishi Seva Kendra", "location": "Indore", "required_quantity": 1500, "deadline": "2026-09-16T10:37:29.944423", "current_inventory": 300, "id": 201, "shortfall": 1200},
  "previous_required_quantity": 1000,
  "shortage_before": 700,
  "shortage_after": 1200,
  "audit_log_id": 2
}
```

### Audit timeline

Every trigger writes a single entry, which is what makes a demo narratable
afterwards:

```json
{
  "actor": "system",
  "action_type": "disruption_injected",
  "details": {
    "disruption": "shipment_delay",
    "shipment_id": 1,
    "delay_hours": 12.0,
    "status": {"before": "PENDING", "after": "DELAYED"},
    "expected_arrival": {"before": "2026-09-14T10:37:29.961483", "after": "2026-09-14T22:37:29.961483"},
    "total_delay_hours": 12.0
  },
  "result": "success",
  "id": 2,
  "timestamp": "2026-09-13T10:37:29.968648"
}
```

## Recovery optimization

`POST /optimize/recovery { shortage_quantity, deadline }` answers "what is the
best way to close this gap?". It is **pure Python and deterministic**: the
module `app/optimizer.py` touches no database, no LLM and no clock (`now` is an
input), so the same state always produces exactly the same ranking.
`app.services.optimizer_service` is the only part that talks to the ORM — it
snapshots warehouse stock, available vendors and open routes into a
`RecoveryState` and hands it over.

Two functions are exposed there: `optimize_recovery(state) -> list[RankedOption]`
(the required entry point, feasible options only) and
`evaluate_recovery(state) -> RecoveryPlan` (same ranking plus the excluded
candidates).

### Candidates

Every candidate is sized to exactly the shortage, so "can it cover the gap?" is
a stock comparison.

| Action | Cost | Delivery time | Carbon |
|---|---|---|---|
| `warehouse_transfer(warehouse_id)` | `distance_km × TRANSPORT_COST_PER_KM` on the warehouse's fastest open route to the dealer | that route's `travel_time_hours` | `distance_km × carbon_per_km` |
| `vendor_purchase(vendor_id)` | `price_per_unit × quantity` | the vendor's `delivery_hours` | `carbon_per_unit × quantity` |

`TRANSPORT_COST_PER_KM` is `30.0`. Goods already in a warehouse still have to
travel, while a vendor's price already includes delivery — this is what makes the
two candidate types comparable. If several routes connect a warehouse to the
dealer the fastest is used (then shortest, then greenest, then lowest id), so the
choice is stable.

### Feasibility

A candidate survives only when it holds enough stock (`available_quantity >=
shortage`) **and** lands on time (`delivery_hours <= hours_available`, where
`hours_available = deadline - now`). A warehouse with no open route to the dealer
is infeasible too. Everything dropped is returned in `excluded` with a stable
reason — `insufficient_quantity`, `misses_deadline`, `no_available_route` — along
with the raw numbers that dropped it, so "why is my option missing?" is always
answerable.

### Scoring

Each metric is min-max normalized across the **feasible** candidates only (lower
is better, so the best value becomes `0` and the worst `1`), then weighted:

```
score = 0.4 × normalized_cost + 0.4 × normalized_delivery_hours + 0.2 × normalized_carbon
```

Lower is better; `0` is the best possible. When every feasible candidate shares a
value for a metric that metric contributes `0` to all of them, and a single
feasible option therefore scores `0`. Ties break deterministically on cost, then
delivery time, then carbon, then action name, then reference id — the ranking
never depends on dictionary or set order.

### POST /optimize/recovery

For the seeded 700-bag shortage with a 72-hour deadline:

```json
{
  "shortage_quantity": 700,
  "deadline": "2026-09-16T10:41:45.166014",
  "hours_available": 72.0,
  "weights": {"cost": 0.4, "delivery_hours": 0.4, "carbon": 0.2},
  "options": [
    {
      "rank": 1, "action": "vendor_purchase", "reference_id": 3, "label": "Bharat Urea Traders", "quantity": 700, "route_id": null,
      "total_cost": 19950.0, "total_delivery_hours": 12.0, "total_carbon": 2940.0,
      "normalized_cost": 1.0, "normalized_delivery_hours": 0.0, "normalized_carbon": 0.0,
      "cost_contribution": 0.4, "delivery_contribution": 0.0, "carbon_contribution": 0.0,
      "score": 0.4
    },
    {
      "rank": 2, "action": "vendor_purchase", "reference_id": 1, "label": "AgroChem Industries", "quantity": 700, "route_id": null,
      "total_cost": 17430.0, "total_delivery_hours": 30.0, "total_carbon": 4550.0,
      "normalized_cost": 0.0, "normalized_delivery_hours": 1.0, "normalized_carbon": 1.0,
      "cost_contribution": 0.0, "delivery_contribution": 0.4, "carbon_contribution": 0.2,
      "score": 0.6
    }
  ],
  "excluded": [
    {"action": "vendor_purchase", "reference_id": 2, "label": "GreenFields Fertilizers", "reason": "insufficient_quantity", "available_quantity": 500, "delivery_hours": 8.0, "hours_available": 72.0},
    {"action": "warehouse_transfer", "reference_id": 101, "label": "Central Depot", "reason": "insufficient_quantity", "available_quantity": 450, "delivery_hours": 9.5, "hours_available": 72.0},
    {"action": "warehouse_transfer", "reference_id": 102, "label": "North Hub", "reason": "insufficient_quantity", "available_quantity": 120, "delivery_hours": 22.0, "hours_available": 72.0},
    {"action": "warehouse_transfer", "reference_id": 103, "label": "East Yard", "reason": "insufficient_quantity", "available_quantity": 600, "delivery_hours": 27.0, "hours_available": 72.0}
  ]
}
```

Reading the breakdown: no warehouse holds 700 and GreenFields only has 500, so
the two vendors that can cover the gap are ranked. Bharat wins because it is both
fast (`12 h → 0`) and green (`2,940 kg → 0`); it is the pricier vendor
(`normalized_cost 1.0`), but cost is only 0.4 of the score. AgroChem is cheapest
(`normalized_cost 0.0`) yet slowest and dirtiest (both `1.0`), so its delivery
and carbon contributions alone (`0.4 + 0.2`) outweigh its cheaper price.

With nothing feasible the ranked list is empty and every candidate is explained:

```json
{
  "shortage_quantity": 5000,
  "hours_available": 72.0,
  "options": [],
  "excluded": [
    {"action": "vendor_purchase", "reference_id": 1, "reason": "insufficient_quantity", "available_quantity": 800},
    {"action": "vendor_purchase", "reference_id": 2, "reason": "insufficient_quantity", "available_quantity": 500},
    {"action": "vendor_purchase", "reference_id": 3, "reason": "insufficient_quantity", "available_quantity": 1200}
  ]
}
```

## Agent layer

The agent orchestrates the layers above and explains the result. Two rules are
absolute and are what the design is built around:

* it **never computes** cost, delivery or carbon — those numbers exist only in
  the Step 5 optimizer, reached through the ``optimize_recovery`` tool;
* it **never invents data** — the shortage and deadline it passes to the
  optimizer are copied straight out of ``get_demand``, and the closing prose is
  generated from the recorded tool results and then checked against them.

### Framework: a custom loop, not a model-driven one

The step order (:func:`observe`, :func:`detect`, :func:`investigate`,
:func:`optimize`, :func:`execute`, :func:`verify`) and the hard replan cap are
policy, not something to leave to a model's discretion, so they live in code in
``app/agent/loop.py``. That keeps the whole agent testable offline with no API
key, and makes the guarantees below provable rather than hoped for. When an LLM
is configured it writes only the final explanation, and its output is verified
before it is shown (see *Grounded explanation*).

### Tools

Ten tools, each a thin wrapper over the endpoint named beside it — no tool
reimplements a rule.

| Tool | Wraps | What it does |
|---|---|---|
| `get_inventory` | `GET /inventory` | Stock per warehouse and dealer |
| `get_vendors` | `GET /vendors` | Vendors with price, delivery, carbon, availability |
| `get_shipments` | `GET /shipments` | Every shipment and its status |
| `get_routes` | `GET /routes` | Every route and its availability |
| `get_demand` | `GET /demand` | Requirement, stock, deadline, shortage, constraint status |
| `optimize_recovery` | `POST /optimize/recovery` | Ranked feasible options — the only source of cost/delivery/carbon |
| `transfer_inventory` | `POST /inventory/transfer` | Validated, atomic stock move |
| `purchase_from_vendor` | `POST /vendor/{id}/purchase` | Validated, atomic vendor purchase |
| `reroute_shipment` | `POST /shipment/{id}/reroute` | Validated, atomic reroute |
| `verify_state` | `GET /demand` + `GET /routes` | Whether the requirement is covered |

The three mutating tools go through `ActionService`, so the agent inherits the
same validation, transaction and audit entry as any other caller — those audit
rows are attributed to `agent`.

### The loop

1. **observe** — `get_demand`, `get_shipments`, `get_routes`.
2. **detect** — read `constraint_violated`. If it is false, log "no action
   needed" and stop without touching anything.
3. **investigate** — `get_vendors`, `get_inventory`, `get_routes`.
4. **optimize** — `optimize_recovery(shortage_quantity=demand["shortage"],
   deadline=demand["deadline"])`, passing the observed numbers through
   unchanged.
5. **execute** — the top-ranked feasible option's tool. A `warehouse_transfer`
   option becomes `transfer_inventory(from_id=<reference_id>,
   to_id=<dealer_id>, quantity=<quantity>)`; a `vendor_purchase` option becomes
   `purchase_from_vendor(vendor_id=<reference_id>, quantity=<quantity>)`.
6. **verify** — `verify_state`. If the requirement is still not covered, or the
   action was refused, the loop returns to step 3, up to a **hard cap of 5
   replan cycles** (a caller may lower it, never raise it). A refused action is
   never retried: if it is top-ranked again the run stops as `action_rejected`.

Outcomes: `no_action_needed`, `resolved`, `no_feasible_option`,
`action_rejected`, `replan_limit_reached`.

### Guardrails

Five rules are enforced in code rather than left to a model's judgement. Each is
an explicit branch in `app/agent/loop.py` and each has tests that fail if it
regresses.

**1. Grounding constraint.** The final prose is validated before it is shown.
`ungrounded_numbers()` extracts every number from the text (costs, quantities,
hours, dates) and checks it against that turn's tool results; if a single figure
is absent from them, the whole answer is discarded and the explainer is asked
once more with the instruction *"Only state numbers that appear in the tool
results below. Do not estimate or infer any figures."* Only if that also fails
does the deterministic template produce the text. The pass is reported as
`grounding` on the response and recorded in the trace.

**2. No silent action.** A mutating tool is reachable only through a validated
`ActionDecision` that `_authorise()` has matched against `optimize_recovery`'s
top-ranked feasible option *from the same cycle* — action, target id and
quantity must all agree. A mismatch is refused and logged under the `guardrail`
phase, no stock-moving tool runs, and the run ends as `decision_rejected`. No
`optimize_recovery` call in the cycle means no mutation, full stop.

**3. Refuse if uncertain.** When the optimizer returns zero feasible options the
loop breaks immediately with `NO_FEASIBLE_MESSAGE` — "No feasible recovery
option meets the current constraints". No decision is requested in that branch,
so no choice can be forced or invented: the honest refusal is a code path, not a
matter of model judgement.

**4. Bounded autonomy.** At most 5 replan cycles per disruption (a caller may
lower `max_replans`, never raise it) and at most 15 tool calls per cycle. Either
budget being exceeded stops the run with its own outcome
(`replan_limit_reached` / `tool_call_limit_reached`) rather than looping; a
refused action is never retried.

**5. Structured output only.** Action selection never parses prose. `decide()`
validates the selector's output against the `ActionDecision` schema (`action`,
`params`, `reasoning`); anything else — free text, a malformed payload, a
missing field — is rejected and logged, and no tool is called. The shipped
`TopRankedSelector` simply echoes the optimizer's ranking, so the default agent
cannot diverge; the schema is what makes a model-backed selector safe to drop in
later.

### Reasoning trace

Every step — tool name, arguments and the **raw, unmodified JSON result** — is
recorded and returned, so the frontend can display exactly what happened and any
figure in the prose can be checked against its source. A refusal is recorded
too, as `{"error": ..., "reason": ...}`.

### Grounded explanation

Two explainers implement one interface. The default `TemplateExplainer` builds
its sentences by reading fields out of the recorded tool results, so every
number in it is interpolated from the trace and it is grounded by construction.
If an LLM is configured (`GROQ_API_KEY`) it may write the explanation instead,
in which case guardrail 1 above governs what reaches the user. Either way there
is exactly one enforcement point — the loop's `_explain()` — so the two cannot
disagree, and if the provider call fails for any reason the template takes over
rather than the run failing. A fallback is never silent: `fallback_reason` names
the cause (missing key, HTTP error, exhausted budget) instead of leaving you to
guess why the prose changed voice.

Groq-specific knobs exist because the default model is a *reasoning* model and
bills its thinking to the same token budget as its answer. Both defaults were set
from measured failures: `AGENT_EXPLAINER_MAX_TOKENS=700` returned an empty
completion (`finish_reason=length`) on this trace and fell back on every run,
and unbounded reasoning made a single summary take anywhere from 3 s to 42 s.
Raising the budget and sending `reasoning_effort=low` gives plain, grounded prose
in about 1–2 s.

### POST /agent/recover

For the seeded scenario (no body needed; `{"max_replans": n}` is optional):

```json
{
  "run_id": "e0b0c6f4-…",
  "outcome": "resolved",
  "replan_cycles": 0,
  "tool_calls": 9,
  "audit_log_ids": [2, 3],
  "grounding": {"attempts": 1, "rejected_numbers": [], "regenerated": false, "fallback_used": false, "fallback_reason": null},
  "explanation": "Dealer Krishi Seva Kendra (201) requires 1000 units by 2026-09-16T10:48:30.463703 and holds 300, a shortage of 700 with 700 units already inbound (constraint_violations=[\"shortage of 700 units (300 of 1000 on hand)\"]). The optimizer ranked vendor_purchase from Bharat Urea Traders (reference_id 3) first for 700 units: cost 19950.0, delivery 12.0 h, carbon 2940.0, score 0.4. Executed purchase_from_vendor({\"vendor_id\": 3, \"quantity\": 700}), which created shipment 2 of 700 units from Bharat Urea Traders arriving 2026-09-13T22:48:30.492105 and left vendor availability at 500 (was 1200). Verification: satisfied=true — on hand 300 plus 1400 inbound by the deadline is 1700 against a requirement of 1000, with late shipments [].",
  "verify": {"required_quantity": 1000, "available_quantity": 300, "on_time_inbound_quantity": 1400, "covered_quantity": 1700, "satisfied": true, "late_shipment_ids": [], "unknown_eta_shipment_ids": [], "constraint_violated": true, "shortage": 700}
}
```

`grounding` reports the validation pass: `attempts: 1` with nothing rejected
means the first draft was already fully traceable. When the demand is spiked
beyond anything on hand (`POST /simulate/demand-spike` to 5000), the same
endpoint refuses honestly instead — `outcome` is `no_feasible_option`,
`actions` is `[]`, `plan.options` is `[]`, and the explanation carries the exact
constant with every candidate's exclusion reason:

```json
{
  "outcome": "no_feasible_option",
  "actions": [],
  "plan": {"options": [], "excluded": [{"action": "vendor_purchase", "reference_id": 1, "reason": "insufficient_quantity", "available_quantity": 800}, {"…": "…"}]},
  "explanation": "Dealer Krishi Seva Kendra (201) requires 5000 units by 2026-09-16T11:06:04.826268 and holds 300, a shortage of 4700 with 700 units already inbound (constraint_violations=[\"shortage of 4700 units (300 of 5000 on hand)\"]). No feasible recovery option meets the current constraints. Excluded candidates: vendor_purchase 1 (insufficient_quantity: available 800), vendor_purchase 2 (insufficient_quantity: available 500), vendor_purchase 3 (insufficient_quantity: available 1200), warehouse_transfer 101 (insufficient_quantity: available 450), warehouse_transfer 102 (insufficient_quantity: available 120), warehouse_transfer 103 (insufficient_quantity: available 600)."
}
```

The trace that produced it (`result` elided here; the real response carries the
full raw JSON for every row):

| # | phase | tool | arguments | note |
|---|---|---|---|---|
| 0 | observe | `get_demand` | `{}` | |
| 1 | observe | `get_shipments` | `{}` | |
| 2 | observe | `get_routes` | `{}` | |
| 3 | detect | | | `constraint_violated=true, investigating recovery options` |
| 4 | investigate | `get_vendors` | `{}` | |
| 5 | investigate | `get_inventory` | `{}` | |
| 6 | investigate | `get_routes` | `{}` | |
| 7 | optimize | `optimize_recovery` | `{"shortage_quantity": 700, "deadline": "2026-09-16T10:48:30.463703"}` | |
| 8 | execute | `purchase_from_vendor` | `{"vendor_id": 3, "quantity": 700}` | |
| 9 | verify | `verify_state` | `{}` | |

The `optimize_recovery` step's raw result is the Step 5 payload verbatim, which
is where every cost/delivery/carbon figure in the explanation came from:

```json
{"options": [{"rank": 1, "action": "vendor_purchase", "reference_id": 3, "label": "Bharat Urea Traders", "quantity": 700, "total_cost": 19950.0, "total_delivery_hours": 12.0, "total_carbon": 2940.0, "score": 0.4, "…": "…"}], "excluded": ["…"]}
```

#### A note on `satisfied` vs `constraint_violated`

`verify_state` reports both, and they can legitimately disagree. `GET /demand`'s
`constraint_violated` is true whenever stock *on hand* falls short of the
requirement, even if inbound shipments already cover it; `satisfied` is a
coverage verdict — on-hand plus inbound arriving by the deadline. In the run
above the dealer is 700 short on hand but 1000 units are inbound in time, so
`satisfied` is true while `constraint_violated` remains true. The comparison is
between numbers the backend already computed; `verify_state` derives no cost,
delivery or carbon metric of its own.

The practical consequence is worth stating plainly: because the optimizer sizes
action from `/demand`'s on-hand shortage, the seeded run buys stock that an
already-inbound shipment would have covered. Closing that gap means having the
optimizer account for in-transit supply (see the follow-up in the design notes).

## Security

A short summary; [`SECURITY.md`](SECURITY.md) has the full measures and the
reasoning behind each.

**Authentication.** Every state-changing endpoint — the action routes, all four
`/simulate/*` triggers, `POST /agent/recover`, `POST /admin/reset`,
`POST /audit-logs` and every CRUD write (**34 operations in total**) — requires
the server's API key in the `X-API-Key` header, as does `GET /audit`. Reads stay
open for the dashboard. The key is compared in constant time and checked *before*
the body is validated, so a malformed request cannot probe which ids exist. Set it
with `API_KEY`; unset is permitted only when `ENVIRONMENT` is `development` or
`test`, so any other deployment refuses to start without one.

One inconsistency is still open, and worth naming rather than glossing: the raw
audit-log CRUD reads (`GET /audit-logs`, `/audit-logs/recent`,
`/audit-logs/{id}`) are **not** gated, so the same trail that `GET /audit`
protects is reachable ungated through those aliases. Gating them — or dropping
them in favour of `/audit` — is the outstanding fix.

```bash
curl -X POST localhost:8000/inventory/transfer \
  -H 'X-API-Key: your-key' -H 'Content-Type: application/json' \
  -d '{"from_warehouse_id": 101, "to_id": 201, "quantity": 50}'
```

**Rate limiting.** `slowapi` limits every endpoint
(`RATE_LIMIT_DEFAULT`, 200/minute) and caps the two caller-driven compute paths
tighter: the agent trigger at `RATE_LIMIT_AGENT` (10/minute, because each call
can spend real money) and the optimizer at `RATE_LIMIT_OPTIMIZE` (60/minute). A
tripped limit answers `429` with `{"detail": ..., "reason": "rate_limited"}`.

**Validation.** Every request and response is a typed Pydantic model with
explicit bounds (`MAX_QUANTITY`, `MAX_HOURS`, `MAX_RATE`, `MAX_DISTANCE_KM` in
`app/schemas/common.py`); unknown ids are `404` with context, never a `500`.

**Agent least privilege.** The LLM has no database, no shell and no HTTP client.
It can only reach the backend through the ten tools in `app/agent/tools.py`, three
of which mutate and all of which route through the same validated
`ActionService`. There is no tool that deletes, drops or resets anything; the
complete surface is published at `GET /agent/tools`.

**CORS.** Restricted to the origins in `CORS_ORIGINS` with explicit methods and
headers; a wildcard is rejected at startup.

## Configuration

All settings come from environment variables (optionally via `.env`) — see
`.env.example`. No secret is hardcoded: `API_KEY` and `GROQ_API_KEY` are optional
and must be injected from the environment (`SECRET_KEY` and `ADMIN_API_KEY` were
removed rather than left in place unused).

`CORS_ORIGINS` accepts either a comma-separated list or a JSON array. The field
is typed as a union on purpose: pydantic-settings JSON-decodes a plain `List[str]`
read from the environment, so the documented `a,b` form would otherwise abort
startup before the validating splitter ran.

| Variable | Default | Meaning |
|---|---|---|
| `APP_NAME` | `supply-chain-agent-backend` | App title |
| `ENVIRONMENT` | `development` | Deployment label; anything else requires `API_KEY` |
| `DEBUG` | `false` | FastAPI debug mode |
| `AUTO_SEED` | `true` | Seed an empty database on startup |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins; `*` rejected |
| `DATABASE_URL` | `sqlite:///./supply_chain.db` | SQLAlchemy URL |
| `SQL_ECHO` | `false` | Log SQL statements |
| `RATE_LIMIT_ENABLED` | `true` | Master switch for the limiter |
| `RATE_LIMIT_DEFAULT` | `200/minute` | Applied to every endpoint |
| `RATE_LIMIT_AGENT` | `10/minute` | `POST /agent/recover` |
| `RATE_LIMIT_OPTIMIZE` | `60/minute` | `POST /optimize/recovery` |
| `API_KEY` | — | Guards every write via `X-API-Key`; required outside development |
| `GROQ_API_KEY` | — | Enables the optional Groq-backed LLM explainer |
| `AGENT_EXPLAINER_MODEL` | `openai/gpt-oss-120b` | Groq model for that explainer |
| `AGENT_EXPLAINER_TIMEOUT` | `30` | Seconds before the explainer gives up and the template takes over |
| `AGENT_EXPLAINER_MAX_TOKENS` | `2048` | Token budget per call; must clear the reasoning burn |
| `AGENT_EXPLAINER_REASONING_EFFORT` | `low` | How long a reasoning model may think; empty omits the field |

## Demo & verification script

`demo.py` drives the whole story through the real HTTP API and prints it as a
narrated log — the backbone for a demo run and the evidence for verification.

```bash
python demo.py                                            # private backend
python demo.py --url http://127.0.0.1:8000 --key $API_KEY  # against a live one
python demo.py --strict                                   # findings fail the run
python demo.py --with-groq                                # LLM narration, from .env
```

The default form is hermetic: it starts its own backend on a free port against a
throwaway database it deletes afterwards, so it needs no running server, no key
and no free port, and can never touch `supply_chain.db`. Pass `--url` when
recording, so the dashboard animates alongside the log. Stdlib only.

It also ignores your `.env`: a `GROQ_API_KEY` there would otherwise make every
attempt wait on a model, and let the wall clock and the prose differ between
runs, which is not what evidence should do. `--with-groq` opts in deliberately —
the child backend then reads the key from `.env` or the shell, requests get a
longer timeout, and the run **fails** if the model did not actually write the
summary rather than passing with template prose.

The run, in order:

| Step | Calls | Checks |
| --- | --- | --- |
| 0 | a write with no key | refused with 401 |
| 1 | `POST /admin/reset` | the documented starting state, and that the scenario is live (shipment 24 h out, deadline 72 h out) |
| 2 | `POST /simulate/shipment-delay` | the shipment is `DELAYED` with an ETA past the deadline, and the violation is reported |
| 3 | `POST /agent/recover` | the run resolves, executes exactly one action, and that action is the optimizer's top-ranked feasible option — tool, target and quantity |
| 4 | `GET /demand` | the requirement is covered end to end |
| 5 | `POST /simulate/route-block` | the lane behind the recovery is blocked |
| 6 | `POST /agent/recover` | the second run reports an outcome and does not blindly repeat the first action |
| 7 | `GET /demand` | requirement covered; every shipment the agent arranged lands before the deadline |
| 8 | `GET /audit` | the trail shows the reset, both disruptions, both runs, every agent mutation attributed to `actor: agent`, with before/after state |

Every assertion is read back out of the API responses — nothing is taken on
trust, and the "no silent action" guardrail is verified from the payload rather
than assumed.

### What it reports rather than asserts

Three things the brief expects do not hold against this system, and the script
says so under `FINDINGS` instead of passing quietly. `--strict` turns them into
failures for CI.

1. **`/demand` does not reach `shortage = 0` after a recovery.** `shortage` is
   on-hand only (`required - available`, the contract from the read-only step),
   and a vendor purchase leaves stock on hand untouched because the goods arrive
   in transit. Coverage completes; `shortage` does not move. A warehouse-transfer
   recovery *would* move it, but the seeded warehouses hold 450 / 120 / 600 — all
   below the 700 shortfall — so no transfer is feasible in this scenario.
2. **A route block cannot invalidate the agent's plan, so `replan = 1` is
   unreachable.** The agent only ever executes the optimizer's top-ranked
   *feasible* option, and neither mutating tool consults routes —
   `transfer_inventory` checks stock, `purchase_from_vendor` checks vendor
   availability. The loop's replan path is therefore reachable only on a race
   between optimization and execution, which a deterministic script cannot
   create. The second run re-ranks from scratch and picks a different vendor,
   at `replan_cycles = 0`.
3. **The agent buys stock nothing needs.** `detect()` gates on the on-hand
   `constraint_violated` flag while `verify_state` judges coverage, and the two
   legitimately disagree here: 300 on hand against a requirement of 1000
   (violated) while 1700 units arrive in time (covered). So a run resolves the
   requirement, is immediately told the constraint is still violated, and buys
   again — 700 units over.   Netting in-transit supply off `shortage` closes this
   and (1) together, and is the single highest-value next change.

## Evaluation summary

`evaluate.py` is the step after the demo: it resets and re-runs the agent N times
with a **randomly parameterised disruption** each time, and prints the table below.
It reuses `demo.py`'s client and backend lifecycle rather than copying them.

```bash
python evaluate.py                        # 8 runs, randomly drawn sample
python evaluate.py --runs 20 --seed 7     # 20 runs on a pinned seed
python evaluate.py --json summary.json    # also write it out for the slides
python evaluate.py --with-groq            # narrate with the LLM (latency included)
```

`--with-groq` puts model latency into the recovery-time column, so the two
invocations answer different questions: the default measures the agent's own
work, the flagged one measures the run a user would actually wait for.

The sample is drawn at random so repeated invocations really do explore different
parameters, and the seed is printed so any sample can be reproduced exactly with
`--seed`. `recovery success rate` counts runs whose requirement ended up covered;
the `resolved` line below it counts runs where the agent acted *and* verified it.

Each run records the agent's outcome, whether the requirement ended up covered,
replans, tool calls, the wall-clock time of the recovery call, and the executed
option's cost / delivery / carbon — the optimizer's own figures, not recomputed
here. Refusals are read back out of `GET /audit` and cross-checked against the run
response, so the numbers quoted are the ones the trail recorded.

### A sample run (`--runs 8 --seed 2026`)

```text
  RUN  DISRUPTION                        OUTCOME                    COVER  REPLAN  CALLS        COST   HOURS     CARBON     WALL
  ---  --------------------------------  -------------------------  -----  ------  -----  ----------  ------  ---------  -------
    1  shipment_delay 31.4h              resolved                   yes         0      9      19,950    12.0      2,940    0.04s
    2  shipment_delay 85h                resolved                   yes         0      9      19,950    12.0      2,940    0.04s
    3  demand_spike -> 2171              no_feasible_option          NO          0      7           0     0.0          0    0.04s
    4  demand_spike -> 1953              no_feasible_option          NO          0      7           0     0.0          0    0.04s
    5  vendor_failure #1 AgroChem Ind.   resolved                   yes         0      9      19,950    12.0      2,940    0.04s
    6  shipment_delay 11.5h              resolved                   yes         0      9      19,950    12.0      2,940    0.05s
    7  shipment_delay 43.7h              resolved                   yes         0      9      19,950    12.0      2,940    0.05s
    8  demand_spike -> 1693              no_feasible_option          NO          0      7           0     0.0          0    0.03s
  TOTAL                                                            5/8         0    8.2      99,750    60.0     14,700     1.9s

  AGENT OUTCOME DISTRIBUTION
  resolved               |##################################|   5   62.5%
  no_feasible_option     |####################..............|   3   37.5%

  KEY METRICS
  Recovery success rate      5/8 runs (62.5%) - requirement covered at the end
  Average recovery time      0.04 s wall clock  (min 0.03 s, max 0.05 s)
  Average replans            0.00 per disruption  (0 total, cap 5)
  Average tool calls         8.2 per run

  COST / DELIVERY / CARBON PER RUN
  average      cost   12,468.8   delivery    7.5 h   carbon   1,837.5
  total        cost   99,750.0   delivery    60.0 h   carbon  14,700.0

  FAILED / REJECTED ACTIONS (read back from GET /audit)
  - run 3: outcome=no_feasible_option (shortage 1871, replans 0, tool_calls 7): the optimizer
    found no feasible candidate, so the agent refused rather than inventing one
  - run 4: outcome=no_feasible_option (shortage 1653, ...)
  - run 8: outcome=no_feasible_option (shortage 1393, ...)

RESULT  39 invariant(s) held, 0 failed, 1.9s of wall clock for 8 runs
```

Read those numbers with their caveats attached, which
[**EVALUATION.md**](EVALUATION.md) sets out in full:

* **The success rate flatters the agent.** A run counts as a success whenever the
  requirement ends up covered — including runs where it was *already* covered
  before the agent acted. Every resolved run cost an identical 19,950 for exactly
  that reason.
* **All three failures are demand spikes**, and all three are the honest-refusal
  path, not crashes: candidates are sized to the whole shortfall and must be
  covered by one source, so a spike beyond the largest supplier (1,200 bags)
  leaves nothing feasible.
* **Replans are 0 everywhere**, which confirms the demo's Finding 2 from the other
  direction: the replan path is unreachable through the public API here.
* **~0.04 s is not a performance claim.** The default explainer is a local
  template and SQLite runs in-process; set `GROQ_API_KEY` and that becomes the
  real cost per run.

[**EVALUATION.md**](EVALUATION.md) has the methodology, the full per-run table,
the failure list with reasons, and the `--json` output shape.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

264 tests cover the exact seeded state (counts, supplier profiles, inventory
levels, dealer shortfall, shipment timing, route availability), reset
repeatability, every create/update/delete path, inventory helpers, status
transitions, audit logging, the read views (inventory totals, vendor ordering
and filtering, every demand rule and constraint case), the 404/409/422 error
paths, and every action above — its happy path, its returned before/after state,
the audit entry it writes, each way it can be refused, and the atomic rollback
that guarantees a change and its audit record commit together or not at all.
The disruption triggers are covered the same way, including that a rejected
trigger changes nothing and adds no audit entry. The optimizer has its own unit
tests against the pure module — no feasible option, a dominant option, both
tie-break rules, min-max normalization over feasible candidates only, warehouse
freight pricing, a cheapest-but-late option being excluded, and order-independent
determinism — plus endpoint tests that check the ranking follows the live
database. The agent is covered end to end: the prescribed phase order, the
detect verdict, replanning after a failed verification, the trace's raw results,
`agent` attribution in the audit log, and the HTTP contract.

Each guardrail has its own tests: a spiked demand where nothing is feasible
asserts the exact refusal, that no decision was requested, that no mutating tool
ran and that the database is untouched; a selector that names a different vendor
or quantity is refused and logged; a refused action is never retried; free text
cannot become a decision; the per-cycle tool budget and the replan cap both stop
the loop; and a "lying" explainer whose invented figure is caught, regenerated
under the grounding instruction and — when it lies again — replaced by the
template.

The security layer has its own suite (`tests/test_security.py`): all 19 mutating
routes reject a missing key and a wrong key and accept the configured one; reads
stay open while `/audit` is gated; the 401 precedes body validation; a
non-development environment refuses to boot without `API_KEY`; the CORS wildcard
is rejected and a stranger's origin gets no header; the agent cap and the 200/minute
default are both tripped for real; the request bounds hold; unknown ids are 404;
a destructive action cannot even be expressed as a decision; injected text in the
scenario cannot drive the agent; and the source is scanned for hardcoded
credentials. Each test runs against its own in-memory SQLite database and never
touches `supply_chain.db`.

`pytest.ini` disables the `pytest-asyncio` and `pytest-flask` plugins because
this stack is fully synchronous and some machines have incompatible global
copies that break collection.

## Design notes

* **Naive UTC everywhere.** SQLite has no timezone support, so all timestamps are
  stored as naive UTC via `app.utils.utcnow()`; mixing aware and naive values
  later would break delay math.
* **JSON columns.** `Warehouse.inventory` and `AuditLog.details` use SQLAlchemy's
  `JSON` type. `inventory` is wrapped in `MutableDict` so in-place edits are
  tracked, and `Warehouse.quantity_of` / `set_quantity` hide the fact that JSON
  object keys come back as strings.
* **One seed function.** The CLI and the reset endpoint both call
  `seed_database()`, so they can never drift apart.
* **Service layer first.** Agent logic in the next milestone can import
  `SupplierService.cheapest_available()` or `WarehouseService.inventory_of()`
  instead of duplicating queries, and can log every step through
  `audit_log_service.record()`.
* **Actions are transactional.** `ActionService` stages the audit entry with
  `audit_log_service.stage()` (which adds it to the session without committing)
  and commits once, so the mutation and its audit record are atomic; any failure
  rolls the whole thing back. Validation runs before the transaction, so a
  refused action never mutates anything.
* **The agent is a loop, not a chatbot.** Its reasoning is orchestration: the
  control flow, the hard replan cap, the no-silent-action guard and the grounding
  check are ordinary code, so they hold whether or not an LLM is configured, and
  the whole agent is testable offline. The LLM, when present, is confined to the
  closing explanation *and* that explanation is validated against the trace before
  it is shown. Known gap: the optimizer sizes actions from `/demand`'s on-hand
  shortage and does not net off in-transit supply, so a gap that an inbound
  shipment already covers can still be acted on.
* **Auth is a dependency, not a middleware.** `require_api_key` is attached per
  route (or per router) rather than intercepting by HTTP method, so the OpenAPI
  schema names exactly which operations require the key — the generated docs list
  32 protected operations — and a new read endpoint is open by default rather
  than accidentally gated. The trade-off is that a new *write* route must
  remember `dependencies=WRITE_GUARD`, so a test reads the generated schema and
  fails if any `POST`/`PUT`/`PATCH`/`DELETE` operation lacks `security` —
  `POST /optimize/recovery` is the single documented exception.
* **The limit is keyed on the peer address.** One bucket per client IP. Behind a
  reverse proxy that does not rewrite the client address, all callers share it —
  acceptable for a demo, and noted in `SECURITY.md`.
