# Evaluation & Verification

How the recovery agent's behaviour was measured, and what the numbers actually
show. Everything here is reproducible with one command — none of it is
hand-written.

```bash
python evaluate.py                        # 8 runs, randomly drawn sample
python evaluate.py --runs 20 --seed 7     # 20 runs on a pinned seed
python evaluate.py --json summary.json    # also write it out for the slides
```

See also: [`demo.py`](#the-single-run-behind-the-video) is the one-scenario script
this summary runs after, and the [README](README.md) covers the system itself.

---

## Method

Each run is independent and does exactly four things:

1. `POST /admin/reset` — back to the documented starting state, so no run inherits
   another's changes. The script asserts the 700-unit shortfall is back before
   every run; that assertion held 8/8 times.
2. Inject **one randomly drawn, randomly parameterised disruption** — a shipment
   delay (1–96 h), a vendor failure, a route block, or a demand spike
   (1,050–2,200 units).
3. `POST /agent/recover` — one agent run, timed with a wall-clock timer.
4. Read back `GET /demand` and `GET /audit` to record what actually happened.

The sample is drawn at random so repeated invocations genuinely explore different
parameters, and the seed is printed (`rerun with --seed N`) so any sample can be
reproduced exactly. Three metrics come from the API rather than being recomputed
here: cost, delivery hours and carbon are the optimizer's own figures for the
option it ranked first, taken from the run response.

Refusals are read out of the audit trail and **cross-checked against the run
response** — the script asserts the trail records the same outcome as the
response on every run, which held 8/8 times. The numbers below are the ones the
trail recorded, not a separate tally.

---

## A sample: 8 runs, seed 2026

```text
  RUN  DISRUPTION                        OUTCOME                    COVER  REPLAN  CALLS        COST   HOURS     CARBON     WALL
  ---  --------------------------------  -------------------------  -----  ------  -----  ----------  ------  ---------  -------
    1  shipment_delay 31.4h              resolved                   yes         0      9     255,500    12.0      2,940    0.04s
    2  shipment_delay 85h                resolved                   yes         0      9     255,500    12.0      2,940    0.04s
    3  demand_spike -> 2171              no_feasible_option          NO          0      7           0     0.0          0    0.04s
    4  demand_spike -> 1953              no_feasible_option          NO          0      7           0     0.0          0    0.04s
    5  vendor_failure #1 AgroChem Ind.   resolved                   yes         0      9     255,500    12.0      2,940    0.04s
    6  shipment_delay 11.5h              resolved                   yes         0      9     255,500    12.0      2,940    0.05s
    7  shipment_delay 43.7h              resolved                   yes         0      9     255,500    12.0      2,940    0.05s
    8  demand_spike -> 1693              no_feasible_option          NO          0      7           0     0.0          0    0.03s
  TOTAL                                                            5/8         0    8.2   1,277,500    60.0     14,700     1.9s
```

### Headline metrics

| Metric | Value |
| --- | --- |
| Recovery success rate | **5 / 8 runs (62.5%)** — requirement covered at the end |
| — of which `resolved` | 5 / 8 (62.5%) — agent acted *and* verified it |
| Average recovery time | **0.04 s** wall clock (min 0.03 s, max 0.05 s) |
| Average replans | **0.00** per disruption (0 total, cap 5) |
| Average tool calls | 8.2 per run |
| Cost | average **159,687.5** · total **1,277,500.0** |
| Delivery time | average **7.5 h** · total **60.0 h** |
| Carbon | average **1,837.5** · total **14,700.0** |
| Invariants checked | 39 held, 0 failed, over 1.9 s |

### Outcome distribution

```text
  resolved               |##################################|   5   62.5%
  no_feasible_option     |####################..............|   3   37.5%
```

### Failed / rejected actions, and why

Read back from `GET /audit` after each run:

| Run | Outcome | Shortfall | Reason |
| --- | --- | --- | --- |
| 3 | `no_feasible_option` | 1,871 | no feasible candidate — the agent refused rather than inventing one |
| 4 | `no_feasible_option` | 1,653 | same |
| 8 | `no_feasible_option` | 1,393 | same |

All three failures are the honest-refusal path, not crashes. Candidates are sized
to the *whole* shortfall and must be covered by a **single** source, so a spike
beyond the largest supplier (1,200 bags) leaves nothing feasible. A purchase
combined with a transfer is not modelled; modelling it is what would lift this
number.

---

## How to read this honestly

The headline 62.5% is real but it is not the whole story, and three things matter
more than the number:

**1. The success metric flatters the agent.** A run counts as a success whenever
the requirement ends up covered — including runs where it was *already* covered
before the agent acted. In run 1 the disruption only delayed the inbound shipment
by 31.4 h, so it still landed ~40 h before the deadline and the 700 units never
stopped covering the shortfall. The agent bought 700 more bags anyway. Every
resolved run cost an identical 255,500 for exactly this reason, and "covered at the
end" scores all of them as wins. A metric that counted *acting when nothing was
required* as a failure would read far lower, and would be the honest one.

**2. Replans are 0 across every run, which is itself a result.** The loop's replan
path is not reachable through the public API in this scenario: the agent only ever
executes the optimizer's top-ranked *feasible* option, and neither mutating tool
consults routes, so a blocked lane cannot invalidate an authorised plan. Replans
only trigger on a race between optimization and execution. This is corroborated
independently by `demo.py`, whose finding 2 reports the same thing from the other
direction.

**3. Recovery time is ~0.04 s, and that is not a performance claim.** The default
explainer is a local template and SQLite runs in-process, so the number measures
loop overhead, not a model call. Set `GROQ_API_KEY` and this becomes the real cost
per run — the honest figure to put on a slide once an LLM writes the prose.

### What this evaluation does not measure

* Combined disruptions — every run injects exactly one, so recovery from two
  simultaneous failures is untested.
* Whether the agent's *explanation* was useful, only that it was grounded (the
  grounding pass itself is asserted in `demo.py`, not here).
* Cost in money. There is no price on a run; `GROQ_API_KEY` unset means no spend
  at all.

---

## The single run behind the video

`demo.py` is the one-scenario counterpart to this sweep, and the run the
presentation scripts against. Its exact numbers are in
[PRESENTATION.md](PRESENTATION.md), and they line up with the table above: the
same 700-unit shortfall, the same 700-unit purchase from Bharat Urea Traders at
₹255,500 / 12.0 h / 2,940 kg carbon, score 0.00, and the same 0 replans.

```bash
python demo.py    # 39 checks, 0 failed, plus 3 reported findings
```

---

## Machine-readable output

`--json PATH` writes the whole thing — every per-run row plus the aggregate:

```json
{
  "seed": 2026,
  "wall_clock_seconds": 1.9,
  "runs": [
    {
      "index": 1, "disruption": "shipment_delay 31.4h", "outcome": "resolved",
      "covered": true, "replans": 0, "tool_calls": 9,
      "action": "vendor_purchase", "quantity": 700,
      "cost": 255500.0, "delivery_hours": 12.0, "carbon": 2940.0,
      "seconds": 0.04, "refusals": [], "audit_outcome": "resolved"
    }
  ],
  "summary": { "runs": 8, "success_rate": 0.625, "average_replans": 0, "total_cost": 1277500.0 }
}
```

The `summary` block carries the same figures as the table above, so a slide deck
or a notebook can read them directly rather than transcribing them by hand.
