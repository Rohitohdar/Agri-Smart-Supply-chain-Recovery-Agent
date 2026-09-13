#!/usr/bin/env python3
"""Evaluation summary — the step after ``demo.py``.

Run it::

    python evaluate.py                       # 8 runs, randomly drawn sample
    python evaluate.py --runs 12 --seed 7    # 12 runs on a pinned seed
    python evaluate.py --json summary.json   # also write it out for the slides
    python evaluate.py --url http://127.0.0.1:8000 --key <API_KEY>

Each run resets to the seeded state, injects **one randomly parameterised
disruption**, lets the agent recover, and records what came back:

* the agent's outcome, and whether the requirement ended up covered
* replans, tool calls, and the wall-clock time of the recovery call
* the executed option's cost, delivery time and carbon, straight from the
  optimizer's ranking
* every failed or refused action and why

Refusals are read back out of ``GET /audit`` and cross-checked against the run
response, so the numbers on the slide are the ones the audit trail recorded.

The client and the backend lifecycle are reused from ``demo.py`` rather than
copied, so there is exactly one owner of how these scripts talk to the API.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from demo import (
    LLM_REQUEST_TIMEOUT_S,
    REQUEST_TIMEOUT_S,
    SEED_SHORTAGE,
    SEED_SHIPMENT_ID,
    Checks,
    Client,
    backend,
    check_authorisation,
    coverage_shortfall,
    log,
    rule,
)

BAR_WIDTH = 34
OUTCOME_COLUMN = 30
DISRUPTION_COLUMN = 32

#: Disruptions this evaluation can inject, one per run.
DISRUPTION_KINDS = ("shipment_delay", "vendor_failure", "route_block", "demand_spike")

#: A spike above roughly 1,900 cannot be covered by any single supplier
#: (the largest holds 1,200), so failure is part of the sample, not a bug.
SPIKE_RANGE = (1_050, 2_200)

DELAY_RANGE = (1.0, 96.0)

#: An outcome that is not a recovery failure: the agent either fixed it or had
#: nothing to fix. Everything else is a refused run and belongs in the report.
SUCCESS_OUTCOMES = frozenset({"resolved", "no_action_needed"})

#: Plain English for each failure code. The audit row stores the code and the
#: run's counters but no free-text reason, so the code is glossed here instead of
#: being guessed at.
OUTCOME_GLOSS = {
    "no_feasible_option": (
        "the optimizer found no feasible candidate, so the agent refused rather "
        "than inventing one"
    ),
    "decision_rejected": (
        "the selected action did not match the optimizer's ranking and was refused"
    ),
    "action_rejected": (
        "the top-ranked action had already been refused, so the run stopped "
        "instead of repeating it"
    ),
    "replan_limit_reached": "the replan cap was reached",
    "tool_call_limit_reached": "the per-cycle tool-call budget was exhausted",
}


@dataclass
class RunOutcome:
    """Everything one evaluated run produced."""

    index: int
    disruption: str
    outcome: str
    covered: bool
    replans: int
    tool_calls: int
    action: Optional[str]
    quantity: Optional[int]
    cost: float
    delivery_hours: float
    carbon: float
    seconds: float
    refusals: list[str] = field(default_factory=list)
    audit_outcome: Optional[str] = None


# --- one run ---------------------------------------------------------------


def inject_disruption(client: Client, rng: random.Random, dealer_id: int) -> str:
    """Inject one randomly parameterised disruption; return a human label."""
    kind = rng.choice(DISRUPTION_KINDS)

    if kind == "shipment_delay":
        hours = round(rng.uniform(*DELAY_RANGE), 1)
        client.post(
            "/simulate/shipment-delay",
            {"shipment_id": SEED_SHIPMENT_ID, "delay_hours": hours},
        )
        return f"shipment_delay {hours:g}h"

    if kind == "vendor_failure":
        available = [v for v in client.get("/vendors") if v["is_available"]]
        vendor = rng.choice(available)
        client.post("/simulate/vendor-failure", {"vendor_id": vendor["id"]})
        return f"vendor_failure #{vendor['id']} {vendor['name']}"

    if kind == "route_block":
        open_routes = [r for r in client.get("/routes") if r["is_available"]]
        route = rng.choice(open_routes)
        client.post("/simulate/route-block", {"route_id": route["id"]})
        return (
            f"route_block #{route['id']} "
            f"{route['from_location_id']}>{route['to_location_id']}"
        )

    requirement = rng.randint(*SPIKE_RANGE)
    client.post(
        "/simulate/demand-spike",
        {"dealer_id": dealer_id, "new_required_quantity": requirement},
    )
    return f"demand_spike -> {requirement}"


def measure_run(
    client: Client, index: int, rng: random.Random, checks: Checks
) -> RunOutcome:
    """Reset, disrupt, recover, and measure — one row of the summary."""
    client.post("/admin/reset")
    demand = client.get("/demand")
    checks.check(
        demand["shortage"] == SEED_SHORTAGE,
        f"run {index}: the reset restored the {SEED_SHORTAGE}-unit shortfall",
        f"shortage={demand['shortage']}",
    )

    disruption = inject_disruption(client, rng, demand["dealer_id"])

    started = time.perf_counter()
    run = client.post("/agent/recover")
    seconds = time.perf_counter() - started

    check_authorisation(checks, run, f"run {index}")

    after = client.get("/demand")
    options = (run.get("plan") or {}).get("options") or []
    executed = [action for action in run.get("actions", []) if action.get("ok")]
    chosen = options[0] if executed and options else None

    refusals = [
        f"{action['tool']} refused: {action.get('reason') or action.get('error')}"
        for action in run.get("actions", [])
        if not action.get("ok")
    ]

    # Read the same run back out of the audit trail and check the two agree.
    audit_outcome = None
    trail = client.get("/audit?limit=200")
    run_entries = [
        entry for entry in trail if entry["action_type"] == "agent_recovery_run"
    ]
    if run_entries:
        details = run_entries[-1]["details"]
        audit_outcome = details.get("outcome")
        for item in details.get("executed", []):
            if not item["ok"]:
                refusals.append(
                    f"{item['tool']} refused (audit: ok=false, no reason recorded)"
                )
    checks.check(
        audit_outcome == run["outcome"],
        f"run {index}: the audit trail records the same outcome as the run response",
        f"audit={audit_outcome} response={run['outcome']}",
    )

    # A run that ends in anything but a recovery *is* the rejected case: nothing
    # was executed, so there is no refused action to list — the outcome is it.
    if audit_outcome not in SUCCESS_OUTCOMES:
        refusals.append(
            f"outcome={audit_outcome} "
            f"(shortage {run['observed_demand']['shortage']}, "
            f"replans {run['replan_cycles']}, tool_calls {run['tool_calls']}): "
            f"{OUTCOME_GLOSS.get(audit_outcome, 'the run did not recover')}"
        )

    return RunOutcome(
        index=index,
        disruption=disruption,
        outcome=run["outcome"],
        covered=coverage_shortfall(after) == 0,
        replans=run["replan_cycles"],
        tool_calls=run["tool_calls"],
        action=chosen["action"] if chosen else None,
        quantity=chosen["quantity"] if chosen else None,
        cost=float(chosen["total_cost"]) if chosen else 0.0,
        delivery_hours=float(chosen["total_delivery_hours"]) if chosen else 0.0,
        carbon=float(chosen["total_carbon"]) if chosen else 0.0,
        seconds=seconds,
        refusals=refusals,
        audit_outcome=audit_outcome,
    )


# --- the summary -----------------------------------------------------------


def summarise(outcomes: list[RunOutcome]) -> dict[str, Any]:
    """Aggregate the runs into the numbers the presentation quotes."""
    total = len(outcomes)
    covered = sum(1 for row in outcomes if row.covered)
    resolved = sum(1 for row in outcomes if row.outcome == "resolved")
    times = [row.seconds for row in outcomes]

    by_outcome: dict[str, int] = {}
    for row in outcomes:
        by_outcome[row.outcome] = by_outcome.get(row.outcome, 0) + 1

    actions: dict[str, int] = {}
    for row in outcomes:
        if row.action:
            actions[row.action] = actions.get(row.action, 0) + 1

    return {
        "runs": total,
        "success_rate": covered / total if total else 0.0,
        "covered": covered,
        "resolved": resolved,
        "outcomes": by_outcome,
        "actions": actions,
        "average_recovery_seconds": statistics.mean(times) if times else 0.0,
        "min_recovery_seconds": min(times) if times else 0.0,
        "max_recovery_seconds": max(times) if times else 0.0,
        "average_replans": (
            statistics.mean([row.replans for row in outcomes]) if total else 0.0
        ),
        "total_replans": sum(row.replans for row in outcomes),
        "average_tool_calls": (
            statistics.mean([row.tool_calls for row in outcomes]) if total else 0.0
        ),
        "total_cost": sum(row.cost for row in outcomes),
        "total_delivery_hours": sum(row.delivery_hours for row in outcomes),
        "total_carbon": sum(row.carbon for row in outcomes),
        "average_cost": statistics.mean([row.cost for row in outcomes]) if total else 0.0,
        "average_delivery_hours": (
            statistics.mean([row.delivery_hours for row in outcomes]) if total else 0.0
        ),
        "average_carbon": (
            statistics.mean([row.carbon for row in outcomes]) if total else 0.0
        ),
        "refusals": [f"run {row.index}: {text}" for row in outcomes for text in row.refusals],
    }


def bar(count: int, largest: int) -> str:
    if largest <= 0:
        return ""
    filled = round(BAR_WIDTH * count / largest)
    return "#" * filled + "." * (BAR_WIDTH - filled)


def render(outcomes: list[RunOutcome], stats: dict[str, Any], elapsed: float, seed: int) -> None:
    rule()
    print(f"EVALUATION SUMMARY - {stats['runs']} runs, seed {seed}")
    rule()
    log(
        "one reset + one randomly parameterised disruption + one agent recovery per run; "
        "cost, delivery and carbon are the optimizer's own figures for the executed option"
    )

    print()
    print(
        f"  {'RUN':>3}  {'DISRUPTION':<{DISRUPTION_COLUMN}}  {'OUTCOME':<{OUTCOME_COLUMN}}  "
        f"{'COVER':<5}  {'REPLAN':>6}  {'CALLS':>5}  {'COST':>10}  {'HOURS':>6}  "
        f"{'CARBON':>9}  {'WALL':>7}"
    )
    print(
        f"  {'-' * 3}  {'-' * DISRUPTION_COLUMN}  {'-' * OUTCOME_COLUMN}  "
        f"{'-' * 5}  {'-' * 6}  {'-' * 5}  {'-' * 10}  {'-' * 6}  {'-' * 9}  {'-' * 7}"
    )
    for row in outcomes:
        print(
            f"  {row.index:>3}  {row.disruption:<{DISRUPTION_COLUMN}}  "
            f"{row.outcome:<{OUTCOME_COLUMN}}  "
            f"{'yes' if row.covered else 'NO':<5}  {row.replans:>6}  {row.tool_calls:>5}  "
            f"{row.cost:>10,.0f}  {row.delivery_hours:>6.1f}  {row.carbon:>9,.0f}  "
            f"{row.seconds:>6.2f}s"
        )
    print(
        f"  {'-' * 3}  {'-' * DISRUPTION_COLUMN}  {'-' * OUTCOME_COLUMN}  "
        f"{'-' * 5}  {'-' * 6}  {'-' * 5}  {'-' * 10}  {'-' * 6}  {'-' * 9}  {'-' * 7}"
    )
    print(
        f"  {'TOTAL':>3}  {'':<{DISRUPTION_COLUMN}}  {'':<{OUTCOME_COLUMN}}  "
        f"{stats['covered']}/{stats['runs']:<3}  {stats['total_replans']:>6}  "
        f"{stats['average_tool_calls']:>5.1f}  {stats['total_cost']:>10,.0f}  "
        f"{stats['total_delivery_hours']:>6.1f}  {stats['total_carbon']:>9,.0f}  "
        f"{elapsed:>6.1f}s"
    )

    print()
    print("  AGENT OUTCOME DISTRIBUTION")
    largest = max(stats["outcomes"].values())
    for outcome, count in sorted(
        stats["outcomes"].items(), key=lambda item: (-item[1], item[0])
    ):
        share = 100 * count / stats["runs"]
        print(f"  {outcome:<22} |{bar(count, largest)}|  {count:>2}  {share:>5.1f}%")

    print()
    print("  KEY METRICS")
    print(
        f"  {'Recovery success rate':<26} {stats['covered']}/{stats['runs']} runs "
        f"({100 * stats['success_rate']:.1f}%) - requirement covered at the end"
    )
    print(
        f"  {'  of which resolved':<26} {stats['resolved']}/{stats['runs']} runs "
        f"({100 * stats['resolved'] / stats['runs']:.1f}%) - agent acted and verified it"
    )
    print(
        f"  {'Average recovery time':<26} {stats['average_recovery_seconds']:.2f} s "
        f"wall clock  (min {stats['min_recovery_seconds']:.2f} s, "
        f"max {stats['max_recovery_seconds']:.2f} s)"
    )
    print(
        f"  {'Average replans':<26} {stats['average_replans']:.2f} per disruption  "
        f"({stats['total_replans']} total, cap 5)"
    )
    print(f"  {'Average tool calls':<26} {stats['average_tool_calls']:.1f} per run")

    print()
    print("  COST / DELIVERY / CARBON PER RUN")
    print(
        f"  {'average':<12} cost {stats['average_cost']:>10,.1f}   "
        f"delivery {stats['average_delivery_hours']:>6.1f} h   "
        f"carbon {stats['average_carbon']:>9,.1f}"
    )
    print(
        f"  {'total':<12} cost {stats['total_cost']:>10,.1f}   "
        f"delivery {stats['total_delivery_hours']:>6.1f} h   "
        f"carbon {stats['total_carbon']:>9,.1f}"
    )
    for name, count in sorted(stats["actions"].items()):
        print(f"  {'executed':<12} {name:<22} x {count}")

    print()
    print("  FAILED / REJECTED ACTIONS (read back from GET /audit)")
    if stats["refusals"]:
        for entry in stats["refusals"]:
            print(f"  - {entry}")
        print()
        print(
            "  note  this is the honest-refusal path, not a crash: with nothing "
            "feasible the\n        agent reports that instead of forcing a choice."
        )
        if "no_feasible_option" in stats["outcomes"]:
            print(
                "  note  candidates are sized to the whole shortfall and must be "
                "covered by one\n        source, so a spike beyond the largest supplier "
                "(1,200 units) has no\n        feasible option. A purchase combined with a "
                "transfer is not modelled,\n        which is why those runs refuse."
            )
    else:
        print("  none - every run either recovered or had nothing to fix")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run N randomised disruptions through the recovery agent and summarise."
    )
    parser.add_argument("--runs", type=int, default=8, help="How many runs (default 8).")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "RNG seed. Left unset the sample is drawn at random and the seed is "
            "printed, so any run can be reproduced exactly with --seed."
        ),
    )
    parser.add_argument("--url", default=None, help="Use an already-running backend.")
    parser.add_argument("--key", default=None, help="API key for that backend.")
    parser.add_argument("--port", type=int, default=None, help="Port for a private backend.")
    parser.add_argument("--json", default=None, help="Also write the summary as JSON here.")
    parser.add_argument(
        "--with-groq",
        action="store_true",
        help=(
            "Let the backend narrate with the configured Groq explainer. Note this "
            "puts model latency into the recovery-time column."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    #: A random default keeps repeated invocations genuinely different samples;
    #: printing it keeps every sample reproducible after the fact.
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    rng = random.Random(seed)
    checks = Checks()

    rule()
    print("SUPPLY CHAIN RECOVERY AGENT - evaluation summary")
    rule()
    print(f"  runs {args.runs}   seed {seed}   disruptions {', '.join(DISRUPTION_KINDS)}")
    if args.seed is None:
        print(f"  rerun with --seed {seed} to reproduce this exact sample")

    timeout = LLM_REQUEST_TIMEOUT_S if args.with_groq else REQUEST_TIMEOUT_S
    with backend(args.url, args.port, args.key, with_groq=args.with_groq) as (
        base_url,
        api_key,
        process,
    ):
        mode = "an already-running backend" if process is None else "a private backend"
        print(f"  backend  {base_url}  ({mode})")
        print(f"  api key  {'configured' if api_key else 'not required (demo mode)'}")
        print(
            "  explainer  "
            + ("Groq (LLM narration)" if args.with_groq else "deterministic template")
        )

        client = Client(base_url, api_key, timeout)
        started = time.perf_counter()
        outcomes = []
        for index in range(1, args.runs + 1):
            outcome = measure_run(client, index, rng, checks)
            outcomes.append(outcome)
            print(
                f"  run {index:>2}/{args.runs}  {outcome.disruption:<{DISRUPTION_COLUMN}}  "
                f"{outcome.outcome:<{OUTCOME_COLUMN}}  {outcome.seconds:.2f}s"
            )
        elapsed = time.perf_counter() - started

    stats = summarise(outcomes)
    render(outcomes, stats, elapsed, seed)

    rule()
    print(
        f"RESULT  {checks.passed} invariant(s) held, {len(checks.failures)} failed, "
        f"{elapsed:.1f}s of wall clock for {stats['runs']} runs"
    )
    rule()
    for failure in checks.failures:
        print(f"  FAIL  {failure}")

    if args.json:
        payload = {
            "runs": [asdict(row) for row in outcomes],
            "summary": stats,
            "seed": seed,
            "wall_clock_seconds": elapsed,
        }
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        print(f"\n  wrote {args.json}")

    print()
    if checks.failures:
        print("EVALUATION FAILED - an invariant broke; the numbers above are not trustworthy.")
        return 1
    print("EVALUATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
