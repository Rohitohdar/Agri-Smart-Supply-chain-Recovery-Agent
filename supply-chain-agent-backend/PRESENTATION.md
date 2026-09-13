# Presentation summary

Everything a reviewer needs in one page: what was built, why it was built that
way, what was hard, and a shot-by-shot script for the demo video whose numbers
match the logged run exactly.

**Companion documents:** [README](README.md) (the system) ·
[SECURITY.md](SECURITY.md) (the security measures) ·
[EVALUATION.md](EVALUATION.md) (the measured results).

---

## 1. Approach

One idea drove every design decision: **the language model must never be the
source of a number, a decision, or a safety property.**

An agent that computes costs and picks actions in its head is untestable and
un-reviewable. So the system is split so that each of those lives in exactly one
place, and every one of them can be exercised without an API key:

| Concern | Where it lives | Why there |
| --- | --- | --- |
| Cost / delivery / carbon arithmetic | `app/optimizer.py` — pure, no DB, no clock | Deterministic and unit-testable; the same input always ranks the same way |
| Whether an action is *allowed* | `app/services/action_service.py` | One validator for every caller, human or agent |
| What the agent does, in order | `app/agent/loop.py` | Policy — the step order and the caps must be provable, not left to a model's discretion |
| What the agent *says* | `app/agent/explain.py` | The only place a model may write prose, and its output is checked before it is shown |

The agent therefore orchestrates and explains. It cannot invent a figure, cannot
call a state-changing tool that the validator has not cleared, and cannot loop
forever. Those are code paths, not prompt instructions — the tests prove them by
construction.

**The LLM is optional.** Unset `GROQ_API_KEY` and a deterministic template writes
the closing explanation, so the whole system runs, demos and tests offline. Set it
and a Groq-hosted model writes the prose — subject to the grounding check in §3,
and with the template still taking over if the provider call fails.

---

## 2. The final solution

Six layers, each usable on its own:

```text
frontend/  React console — live status, disruption controls, reasoning trace
     │  (X-API-Key on every write)
app/routers/       FastAPI endpoints, typed schemas, auth + rate limits
app/services/      validation, transactions, audit entries  ← the only mutator
app/agent/         tools → loop → trace → grounding check
app/optimizer.py   pure ranking: candidates → feasibility → weighted score
app/db/            SQLAlchemy models + the resettable seed scenario
```

**The tool list** — ten tools, each a thin wrapper over the endpoint it names, so
the agent inherits exactly the validation a human caller gets. The full catalogue
is published at `GET /agent/tools`.

| Tool | Wraps | Mutating |
| --- | --- | --- |
| `get_demand`, `get_inventory`, `get_vendors`, `get_shipments`, `get_routes` | the matching `GET` | no |
| `optimize_recovery(shortage_quantity, deadline)` | `POST /optimize/recovery` | no — the only source of cost/delivery/carbon |
| `verify_state()` | `GET /demand` + `GET /routes` | no |
| `transfer_inventory(from_id, to_id, quantity)` | `POST /inventory/transfer` | **yes** |
| `purchase_from_vendor(vendor_id, quantity)` | `POST /vendor/{id}/purchase` | **yes** |
| `reroute_shipment(shipment_id, new_route_id)` | `POST /shipment/{id}/reroute` | **yes** |

**The loop** runs the prescribed phases — observe → detect → investigate →
optimize → decide → execute → verify — and every call, its arguments and its raw
JSON result land in a reasoning trace the console renders in plain language.

**Security in one line:** 34 state-changing operations require an API key in
constant time, the agent trigger is rate-limited at 10/min because each call can
spend money, and the agent has no database, shell or HTTP client of its own — the
ten tools above are its entire reach. Details in [SECURITY.md](SECURITY.md).

---

## 3. Challenges faced

Three problems were genuinely hard, and the fixes shaped the architecture.

### 3.1 Stopping the agent from hallucinating numbers

The natural design — let the model write the summary — produces confident prose
citing figures that appear nowhere in the data. Asserting "don't make things up"
in a prompt is not a control.

**What was done instead:** the final explanation is *validated*. Every numeric
token in the model's prose is extracted and checked against the serialized
reasoning trace. Any untraceable figure discards the entire answer, which is
re-asked once with an explicit instruction (`Only state numbers that appear in the
tool results below. Do not estimate or infer any figures.`). If the second attempt
also cites something untraceable, a deterministic template produces the text — it
is grounded by construction, because it interpolates fields straight out of the
recorded results.

The pass is reported on every response (`attempts`, `rejected_numbers`,
`regenerated`, `fallback_used`), so a reader can see whether grounding had to
intervene. A test feeds in a deliberately lying explainer claiming *"the dealer
needs 424242 units, so I bought 999999 bags"* and asserts both figures are
rejected and that neither reaches the output.

### 3.2 Keeping replanning bounded

Replanning is where agents burn money and hang. Two caps are enforced in the loop
itself, checked *before* each call so a cycle cannot overshoot: **5 replan cycles**
and **15 tool calls per cycle**, each with its own distinct terminal outcome. A
caller may lower the replan cap, never raise it. A refused action is never
retried — if it ranks first again the run ends as `action_rejected` rather than
looping.

Related, and deliberate: when the optimizer finds nothing feasible, the loop
breaks *before* any decision is requested, reporting
`No feasible recovery option meets the current constraints`. The agent cannot
force a choice it cannot validate — that is an explicit branch, not a judgement
call.

### 3.3 Making an LLM's decision safe to execute

If a model can name the next action, a bad ranking becomes a real purchase. The
fix is two-stage: the selector must return JSON validated against an
`ActionDecision` schema (structured output only), **and** the loop then authorises
it against the optimizer's top-ranked feasible option from the same cycle — tool,
target *and* quantity must all agree, or the call is refused and logged. The
shipped selector simply echoes the ranking, so the default agent cannot diverge;
the schema is what makes a model-backed selector safe to drop in later.

### 3.4 An honest carve-out: the two verdicts that disagreed

Not every challenge was solved. `/demand` computes `shortage` from stock **on
hand**, while `verify_state` judges coverage — on hand *plus* whatever arrives by
the deadline. Both are defensible readings of the original spec, and they
legitimately disagree on this scenario: the dealer is 700 short on hand while
1,000 units are inbound in time.

The consequence is real and measured: the agent resolves the requirement, is
immediately told the constraint is still violated, and buys again — **700 bags
more than anything needed** (see [EVALUATION.md](EVALUATION.md), "How to read this
honestly"). Rather than hide it behind a rounded success rate, the demo script
reports it as finding 3 and the evaluation names it as the metric's flaw. Netting
in-transit supply off `shortage` is the single change that closes both.

---

## 4. Conclusion

The system delivers what the brief asked for and, more importantly, it can be
*checked*:

* **The agent's behaviour is deterministic and offline-testable.** 264 tests
  cover the seed contract, every action's happy path, its refusals and their
  rollback, the optimizer's ranking rules, and the agent's outcomes and
  guardrails. No API key is required to run any of them.
* **Every mutating action is validated before it is applied, atomic when it is,
  and audited after.** A rejected action leaves no trace; an accepted one cannot
  land without its audit entry.
* **Nothing the agent says has to be taken on trust.** Numbers are traced to tool
  results, decisions to the optimizer's ranking, and outcomes to the audit trail.
* **Failures are honest.** 3 of the 8 logged runs refuse rather than guess, and
  the demo reports three real gaps instead of quietly passing.

Where it falls short is equally clear — the two verdicts above, no combined
purchase-plus-transfer candidate, and a success metric that counts action taken
on an already-covered requirement as a win. Each is named, reproducible, and
attached to a next step.

---

## 5. Demo video script

Shot by shot, against the exact run in [EVALUATION.md](EVALUATION.md). Every
number below is verbatim from `python demo.py` (run id
`7b1488b2-5f84-4ba7-ac7d-911fcc575a70`), so the video and the logged data cannot
drift apart. Total runtime ≈ 2 minutes; the demo itself executes in ~1 second, so
hold each beat on screen.

Run this first so the console is live: `uvicorn app.main:app`, then `python demo.py`.

---

### Beat 1 — GOAL · *20s*

**On screen:** the console's status panel, freshly reset.

**Say:** "One dealer, Krishi Seva Kendra in Indore, needs 1,000 bags of urea by
September 16th at 12:19. They hold 300. The shortfall is 700 bags. Those 700 are
already on the way — shipment 1 left Central Depot and lands September 14th at
12:19, comfortably inside the deadline. Four routes are open and all three vendors
are available.

"So the plan is fine — until it isn't. We delay that shipment by 60 hours. It now
lands September 17th at 00:19: **twelve hours past the deadline**. The 700 bags
that covered the shortfall no longer count. Nothing covers it."

| | |
| --- | --- |
| Requirement | 1,000 bags |
| On hand / shortfall | 300 / **700** |
| Shipment 1 | 700 bags, ETA Sep 14 12:19 → **delayed to Sep 17 00:19 (12.0 h late)** |
| Deadline | Sep 16 12:19 |

---

### Beat 2 — DECISION · *25s*

**On screen:** the agent feed filling in — observe → detect → investigate →
optimize.

**Say:** "The agent observes the state and detects the violation. It investigates
what is actually available — three vendors, three warehouses, four routes — and
then it does *not* do arithmetic. It hands the real shortage and the real deadline
to the optimizer, and the optimizer ranks every candidate."

Six candidates exist; **four are excluded**, because no single source holds 700
bags — the warehouses hold 450, 120 and 600, and one vendor holds 500.

**Say:** "Two options survive, and the top-ranked one is a purchase of 700 bags
from Bharat Urea Traders: **₹19,950, 12 hours, 2,940 kg of carbon, score 0.40**.

"Note what the scoring did: AgroChem is cheaper at ₹17,430, but it is 30 hours out
and dirtier. With cost and time weighted equally, paying ₹2,520 more buys 18 hours
— so Bharat wins. The agent didn't decide that. The optimizer did."

---

### Beat 3 — ACTION · *15s*

**On screen:** the `EXECUTE` row in the trace, and audit entry **#3**.

**Say:** "The decision is validated as structured JSON and authorised against that
ranking — tool, target and quantity all have to match, or it is refused. It
matches. The agent calls `purchase_from_vendor` for vendor 3, quantity 700.

"Shipment 2 is created, landing September 14th at 00:19. Bharat's stock drops from
1,200 to 500. And audit entry 3 records it as actor **`agent`** — it cannot act
without leaving a signed trace."

---

### Beat 4 — INTERMEDIATE RESULT · *20s*

**On screen:** the `VERIFY` row, then the status panel.

**Say:** "The agent re-reads the state and verifies itself: on hand 300 plus 700
inbound by the deadline is **1,000 against a requirement of 1,000** —
`satisfied: true`, with the late shipment correctly listed. Outcome `resolved`,
zero replans, nine tool calls.

"One thing I want to be straight about on camera: `/demand` still reports a
shortfall of 700. That figure counts **stock on hand only**, and a purchase lands
in transit, so it does not move. The requirement is genuinely covered — the two
numbers answer different questions, and the system reports both rather than
hiding the disagreement."

---

### Beat 5 — ADAPTATION · *30s*

**On screen:** block route 1, then run the agent again.

**Say:** "Now we invalidate the world it planned against. We block route 1, the
lane into the dealer.

"The agent runs again and re-ranks from scratch. **Bharat is out** — it only has
500 bags left after our purchase, and we need 700. The top option is now AgroChem
at ₹17,430, and it executes that instead.

"Being precise about what just happened, because it matters: the plan changed
because the *stock* changed, not because the route block invalidated it. Routing
never enters into a vendor purchase, so the agent **re-ranked rather than
replanned** — replans are 0, not 1. Our demo script reports that as finding 2
instead of claiming a replan it didn't perform."

---

### Beat 6 — FINAL OUTCOME · *20s*

**On screen:** the audit trail, all seven entries, then the result line.

**Say:** "Final state: coverage **1,700 bags against a requirement of 1,000**, and
every shipment the agent arranged lands before the deadline. Seven audit entries —
one reset, two disruptions, two purchases, two agent runs — every mutation
attributed and timestamped. Thirty-nine checks passed, zero failed.

"And the honest ending: it bought 700 bags nothing needed. That is finding 3 in
the run log — the divergence from beat 4, showing up as real waste. That is the
next thing to fix, and the evaluation says so too: the success metric counts a
recovery on an already-covered requirement as a win."

---

## 6. What we would do next

In priority order, each one already evidenced by a logged result:

1. **Net in-transit supply off `shortage`** — closes findings 1 and 3 together,
   makes `detect()` and `verify_state` agree, and stops the unnecessary purchase.
2. **Model combined candidates** (a purchase *and* a transfer) — the three refused
   runs in the evaluation are demand spikes no single source can cover.
3. **Count unnecessary action as failure** in the evaluation, so the headline
   success rate stops flattering the agent.
4. **Make the replan path reachable** — either route-aware actions, or drop the
   machinery and say so. Right now it is defensive code the demo can never
   trigger.
