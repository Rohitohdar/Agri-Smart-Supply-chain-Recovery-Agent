# Problem & Solution Brief

**Project:** Agri Smart Supply-Chain Recovery Agent
**Stack:** FastAPI + SQLAlchemy/SQLite (backend) · React + TypeScript + Vite (console)

---

## 1. The problem

An agricultural dealer — say a fertilizer retailer in Indore — has promised farmers a delivery:
**1,000 bags of urea within 72 hours**. It holds 300. The missing 700 are already on a truck.
The plan is fine — *until it isn't*.

Real supply chains break constantly, in boring but costly ways:

| Disruption | What it means on the ground |
|---|---|
| **Shipment delay** | The truck carrying the 700 bags slips by 60 hours — it now arrives *after* the deadline |
| **Vendor failure** | The backup supplier suddenly has no stock |
| **Route block** | The road to the dealer is closed |
| **Demand spike** | The dealer now needs 1,500 bags, not 1,000 |

Someone then has to answer, quickly: *what is the fastest, cheapest, cleanest way to still make
the delivery?* Today that answer comes from phone calls, spreadsheets and guesswork. A wrong
guess means a missed deadline for farmers, or panic-buying at triple the price.

---

## 2. Why it is hard to automate

1. **The numbers must be real.** A planner that invents a price or an ETA is worse than no planner.
2. **Recovery actions are risky.** Buying stock or moving inventory changes the real world — the
   system must not be allowed to act on a bad idea, loop forever, or hide what it did.
3. **There are trade-offs.** The cheapest option is often the slowest or the most polluting.
   The decision needs a consistent, explainable policy — not vibes.

---

## 3. The solution — in one line

> An agent that **detects** the violated constraint, **ranks** every feasible recovery option with
> a deterministic cost/delivery/carbon optimizer, **executes** the best one through validated and
> audited actions, and **explains itself** in plain language where every number can be traced back
> to the data it came from.

The language model never computes a figure, never invents one, and never decides alone.
All arithmetic lives in a **pure optimizer** (no database, no clock, no LLM); all risk lives behind
a **validator** that refuses infeasible actions; all honesty lives in an **audit trail** and a
**grounding check** on the agent's final explanation.

---

## 4. How it works

```
disruption injected →
  OBSERVE    read demand, shipments, routes from live data
  DETECT     is the dealer's constraint violated?
  INVESTIGATE  what stock, vendors and lanes actually exist right now?
  OPTIMIZE   rank every feasible option: 40% cost + 40% delivery time + 20% carbon
  EXECUTE    run the top-ranked action (transfer / purchase / reroute) — validated, atomic, audited
  VERIFY     re-read the state; if still short, replan (max 5 cycles), else report the outcome
```

**Seed scenario.** One dealer needs 1,000 bags in 72 h and holds 300. Three vendors with different
price/speed/carbon trade-offs, three warehouses with different stock, four routes. One `POST`
resets to this state, so demos and tests always start identical.

**Recovery actions.** `transfer` stock between locations, `purchase` from a vendor,
`reroute` an in-flight shipment, `cancel` one that will not make it. Each is refused with a
machine-readable reason (`insufficient_stock`, `route_unavailable`, …) when infeasible — and a
refused action leaves *no trace*, because the change and its audit entry commit in one transaction.

---

## 5. What makes this trustworthy (the differentiators)

| Risk | How the system closes it |
|---|---|
| Agent hallucinates numbers | Every figure in the final prose is extracted and **checked against the recorded tool results**; anything untraceable discards the whole answer and it is regenerated, then a deterministic template takes over |
| Agent takes an unauthorised action | A decision must match the optimizer's top-ranked option — same tool, target and quantity — or it is refused before any tool runs |
| Agent loops forever / burns money | Hard caps: 5 replan cycles, 15 tool calls per cycle; a refused action is never retried; the agent endpoint is rate-limited to 10 calls/min |
| Agent has too much power | The LLM has **no database, shell or HTTP client** — ten tools are its entire reach, and the three mutating ones go through the same validator a human uses |
| Silent, unauditable changes | Every mutation writes an audit entry (before/after state, actor `agent` or `system`) **in the same transaction** as the change itself |
| Requires a paid API to even run | `GROQ_API_KEY` is optional — unset, a local template writes the explanation and the entire system (and all 264 tests) run offline |

---

## 6. What was built

- **Backend (Python · FastAPI · SQLAlchemy · SQLite):** full CRUD for products, suppliers,
  warehouses, dealers, routes and shipments; read-only decision views (`/inventory`, `/vendors`,
  `/demand`); four validated recovery actions; four disruption triggers; the deterministic
  recovery optimizer; the agent layer (tools, loop, trace, grounded explanation); API-key auth on
  all 34 write operations, rate limiting, and a complete audit trail.
- **Operator console (React + TypeScript):** live system status polled from the API, one-click
  disruption buttons, and the agent's reasoning trace rendered step by step in plain language —
  with a *view tool call* toggle that shows the raw JSON behind every claim.
- **Verification:** 264 offline tests; `demo.py` runs the scripted scenario with 39 assertions;
  `evaluate.py` sweeps N randomized disruption runs and reports success rate, cost, delivery
  time and carbon per run.

---

## 7. Results (from `python evaluate.py`, 8 runs, seed 2026)

| Metric | Result |
|---|---|
| Recovery success (requirement covered at end) | **5 / 8 runs** |
| Recovery time | **~0.04 s** per run (loop overhead; no LLM call by default) |
| Replans used | 0 (cap: 5) — every run resolved on the first ranking |
| Typical action | 700 bags from Bharat Urea Traders — **₹255,500, 12 h, 2,940 kg CO₂, score 0.00** |
| Failures | 3 × `no_feasible_option` — demand spikes **no single source can cover**; the agent **refused honestly** rather than inventing an action |

**Read honestly:** the 62.5% counts a recovery on an already-covered requirement as a win, and
the two verdicts (`shortage` on-hand vs `satisfied` coverage) legitimately disagree mid-run.
Both are named, measured, and attached to a next step rather than hidden — see
[EVALUATION.md](supply-chain-agent-backend/EVALUATION.md).

---

## 8. What we would do next

1. **Net in-transit supply off `shortage`** so detection and verification agree — stops one
   class of unnecessary purchase.
2. **Model combined candidates** (a purchase *and* a transfer) — this is what lifts the three
   honest refusals into successes.
3. **Count unnecessary action as failure** in the evaluation metric, so the headline number
   stops flattering the agent.
4. **LLM-backed decision selector** behind the already-shipped structured-output schema, so a
   model can argue for an option — and still cannot diverge from the validated ranking.

---

*See also: [project architecture](project-architecture.md) · [demo video script](demo-video-script.md) ·
[full evaluation](supply-chain-agent-backend/EVALUATION.md) · [security measures](supply-chain-agent-backend/SECURITY.md)*
