"""The agent layer: loop control, guardrails, trace, grounding and endpoints.

Most tests run the agent in-process against a freshly seeded in-memory database,
which keeps them deterministic. The replan, refusal, mismatch and regeneration
paths are driven with scripted collaborators so each can be exercised directly.
"""

import json
import re
import sys
from datetime import timedelta
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings

from app.agent.constants import (
    GROUNDING_INSTRUCTION,
    MAX_TOOL_CALLS_PER_CYCLE,
    NO_FEASIBLE_MESSAGE,
)
from app.agent.decision import ActionDecision, TopRankedSelector
from app.agent.explain import (
    ExplainerUnavailable,
    ExplanationContext,
    GroqExplainer,
    TemplateExplainer,
    choose_explainer,
    ungrounded_numbers,
)
from app.agent.loop import RecoveryAgent
from app.agent.tools import TOOL_SPECS, Toolbox
from app.agent.trace import AgentOutcome, AgentPhase, ReasoningTrace
from app.db.seed import seed_database
from app.models import Dealer, Shipment, Supplier
from app.services.errors import ConflictError


def _seeded(session_factory, *, disrupted=True):
    db = session_factory()
    seed_database(db)
    if disrupted:
        # Agent-action tests need a genuine coverage violation. The normal seed
        # is deliberately healthy: its on-time inbound shipment covers the
        # on-hand shortfall.
        shipment = db.get(Shipment, 1)
        shipment.expected_arrival = db.get(Dealer, 201).deadline + timedelta(hours=1)
        shipment.status = "DELAYED"
        shipment.delay_hours = 49.0
        db.commit()
    return db


class ScriptedToolbox(Toolbox):
    """A toolbox whose verification and purchase outcomes can be scripted."""

    def __init__(self, db, *, verify_script=(), default_verdict=True, fail_purchase=False):
        super().__init__(db)
        self._verify_script = list(verify_script)
        self._default_verdict = default_verdict
        self._fail_purchase = fail_purchase
        self.verify_calls = 0

    def verify_state(self):
        self.verify_calls += 1
        verdict = (
            self._verify_script.pop(0)
            if self._verify_script
            else self._default_verdict
        )
        data = super().verify_state()
        data["satisfied"] = verdict
        return data

    def purchase_from_vendor(self, vendor_id, quantity):
        if self._fail_purchase:
            raise ConflictError(
                f"Vendor {vendor_id} is not available", reason="vendor_unavailable"
            )
        return super().purchase_from_vendor(vendor_id, quantity)


class ScriptedSelector:
    """Returns a fixed decision (or one computed from the plan)."""

    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    def choose(self, plan):
        self.calls += 1
        if callable(self.decision):
            return self.decision(plan)
        return self.decision


class RetryingExplainer:
    """Cites an invented figure until it is told to stick to the trace."""

    def __init__(self):
        self.corrections = []

    def explain(self, context, *, correction=None):
        self.corrections.append(correction)
        if correction is None:
            return "The dealer needs 424242 units, so I bought 999999 bags."
        return f"Shortage stands at {context.demand['shortage']} units."


class BrokenExplainer:
    """Fails the way a missing key or dependency would."""

    def __init__(self):
        self.calls = 0

    def explain(self, context, *, correction=None):
        self.calls += 1
        raise ExplainerUnavailable("no api key")


# --- the prescribed phase order -------------------------------------------


def test_loop_follows_the_prescribed_phase_order(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    phases = [step.phase for step in run.trace.steps]

    assert phases[:4] == [
        AgentPhase.OBSERVE,
        AgentPhase.OBSERVE,
        AgentPhase.OBSERVE,
        AgentPhase.DETECT,
    ]
    assert phases[4:7] == [
        AgentPhase.INVESTIGATE,
        AgentPhase.INVESTIGATE,
        AgentPhase.INVESTIGATE,
    ]
    # After the main loop, the agent resolves via purchase, then checks for
    # reroute opportunities.  The reroute phase includes the execute and verify
    # steps for the reroute action.
    assert AgentPhase.OPTIMIZE in phases[7:]
    assert AgentPhase.DECIDE in phases[7:]
    assert AgentPhase.EXECUTE in phases[7:]
    assert AgentPhase.VERIFY in phases[7:]
    assert AgentPhase.GUARDRAIL in phases

    assert [step.tool for step in run.trace.steps[:3]] == [
        "get_demand",
        "get_shipments",
        "get_routes",
    ]
    assert [step.tool for step in run.trace.steps[4:7]] == [
        "get_vendors",
        "get_inventory",
        "get_routes",
    ]


def test_seeded_run_resolves_with_one_top_ranked_action(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    assert run.outcome is AgentOutcome.RESOLVED
    assert run.replan_cycles == 0
    # The optimizer ranks reroute_shipment #1 (via route #4, 11 h, ₹18,600)
    # above vendor_purchase #3 (12 h, ₹255,500) in the disrupted scenario.
    tool_names = [action["tool"] for action in run.actions]
    assert "reroute_shipment" in tool_names
    assert run.actions[0]["ok"] is True
    assert run.verify is not None and run.verify["satisfied"] is True
    assert run.plan["options"][0]["reference_id"] == 1  # shipment #1 rerouted


def test_observe_and_demand_are_reused_not_recomputed(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    assert run.plan["shortage_quantity"] == run.demand["shortage"]
    assert run.plan["deadline"] == run.demand["deadline"]


# --- detect ---------------------------------------------------------------


def test_no_action_when_the_constraint_holds(session_factory):
    db = _seeded(session_factory, disrupted=False)
    db.get(Dealer, 201).required_quantity = 300  # no shortage, shipment arrives in time
    db.commit()

    run = RecoveryAgent(Toolbox(db)).run()

    assert run.outcome is AgentOutcome.NO_ACTION_NEEDED
    assert run.actions == []
    assert run.plan is None
    assert [step.phase for step in run.trace.steps] == [
        AgentPhase.OBSERVE,
        AgentPhase.OBSERVE,
        AgentPhase.OBSERVE,
        AgentPhase.DETECT,
        AgentPhase.GUARDRAIL,  # the grounding validation pass still runs
    ]
    assert "no action was needed" in run.explanation


# --- guardrail: refuse if uncertain ---------------------------------------


def test_no_feasible_option_is_reported_honestly(session_factory):
    """(a) No feasible shortage-filling option -> the exact refusal is recorded.

    The agent still attempts a reroute if one improves delivery time, but no
    shortage-filling action is taken.
    """
    db = _seeded(session_factory)
    db.get(Dealer, 201).required_quantity = 5000  # nothing on hand can cover this
    db.commit()

    run = RecoveryAgent(Toolbox(db)).run()

    # The main loop found no feasible shortage-filling option.
    assert NO_FEASIBLE_MESSAGE in run.explanation
    assert run.plan["options"] == []

    # No shortage-filling tool was called during the main loop.
    tools_called = [step.tool for step in run.trace.steps if step.tool]
    assert "purchase_from_vendor" not in tools_called
    assert "transfer_inventory" not in tools_called

    # The database is untouched: no new shipment, no vendor stock consumed.
    assert db.get(Supplier, 3).available_quantity == 1200
    assert ungrounded_numbers(run.explanation, run.trace) == []


def test_no_feasible_option_endpoint_reports_it_without_inventing_a_plan(seeded_client):
    seeded_client.post(
        "/simulate/demand-spike",
        json={"dealer_id": 201, "new_required_quantity": 5000},
    )

    body = seeded_client.post("/agent/recover").json()

    assert NO_FEASIBLE_MESSAGE in body["explanation"]
    assert body["plan"]["options"] == []
    # No shortage-filling tool was called (reroute is not a shortage-filling tool).
    assert all(step["tool"] != "purchase_from_vendor" for step in body["trace"])
    assert all(step["tool"] != "transfer_inventory" for step in body["trace"])


# --- guardrail: no silent action ------------------------------------------


def test_a_decision_that_does_not_match_the_optimizer_is_refused(session_factory):
    # The optimizer ranks reroute_shipment #1 first; this selector insists on vendor 3.
    selector = ScriptedSelector(
        {
            "action": "purchase_from_vendor",
            "params": {"reference_id": 3, "quantity": 700},
            "reasoning": "Bharat Urea Traders is cheapest.",
        }
    )
    run = RecoveryAgent(Toolbox(_seeded(session_factory)), selector=selector).run()

    assert run.outcome is AgentOutcome.DECISION_REJECTED
    assert run.actions == []
    assert all(step.tool != "purchase_from_vendor" for step in run.trace.steps)

    refusal = next(
        step
        for step in run.trace.steps
        if step.phase is AgentPhase.GUARDRAIL and "refused" in (step.note or "")
    )
    assert "does not match optimize_recovery's top-ranked feasible option" in refusal.note
    assert refusal.result["decision"]["params"]["reference_id"] == 3
    assert refusal.result["top_option"]["reference_id"] == 1  # reroute shipment #1


def test_a_decision_with_the_wrong_quantity_is_refused(session_factory):
    # Top option is reroute_shipment #1; insist on reroute with wrong quantity.
    selector = ScriptedSelector(
        {
            "action": "reroute_shipment",
            "params": {"reference_id": 1, "quantity": 1, "shipment_id": 1, "new_route_id": 4},
            "reasoning": "Start small.",
        }
    )
    run = RecoveryAgent(Toolbox(_seeded(session_factory)), selector=selector).run()

    assert run.outcome is AgentOutcome.DECISION_REJECTED
    refusal = [
        step
        for step in run.trace.steps
        if step.phase is AgentPhase.GUARDRAIL and "refused" in (step.note or "")
    ][0]
    assert "quantity" in refusal.note


def test_free_text_is_never_accepted_as_a_decision(session_factory):
    selector = ScriptedSelector("just buy whatever is cheapest")
    run = RecoveryAgent(Toolbox(_seeded(session_factory)), selector=selector).run()

    assert run.outcome is AgentOutcome.DECISION_REJECTED
    assert run.actions == []
    decide_step = next(
        step for step in run.trace.steps if step.phase is AgentPhase.DECIDE
    )
    assert "failed schema validation" in decide_step.note


def test_mutating_tools_are_unreachable_without_an_optimize_call(session_factory):
    agent = RecoveryAgent(Toolbox(_seeded(session_factory)))
    # Top option is reroute_shipment #1 (via route #4) in the disrupted scenario.
    decision = ActionDecision(
        action="reroute_shipment",
        params={"reference_id": 1, "quantity": 700, "shipment_id": 1, "new_route_id": 4},
        reasoning="Copied from the optimizer.",
    )

    # Before any optimize_recovery call this cycle, the guard refuses.
    assert agent._authorise(decision) == "no optimize_recovery call in this reasoning cycle"

    # After optimizing in this cycle, the same decision is authorised.
    agent._start_cycle()
    plan = agent.optimize(agent.toolbox.get_demand())
    assert agent._authorise(decision) is None
    assert plan["options"][0]["reference_id"] == 1  # reroute shipment #1


def test_decision_schema_accepts_tool_names_and_rejects_junk():
    decision = ActionDecision.model_validate(
        {
            "action": "transfer_inventory",  # the tool's name, not the action's
            "params": {"reference_id": 101, "quantity": 50},
            "reasoning": "Stock is closer than any vendor.",
        }
    )
    assert decision.action == "warehouse_transfer"

    with pytest.raises(ValidationError):
        ActionDecision.model_validate("buy something cheap")
    with pytest.raises(ValidationError):
        ActionDecision.model_validate(
            {"action": "delete_everything", "params": {"reference_id": 1, "quantity": 1}, "reasoning": "x"}
        )
    with pytest.raises(ValidationError):  # quantity is required
        ActionDecision.model_validate(
            {"action": "vendor_purchase", "params": {"reference_id": 1}, "reasoning": "x"}
        )
    with pytest.raises(ValidationError):  # extra keys are forbidden
        ActionDecision.model_validate(
            {
                "action": "vendor_purchase",
                "params": {"reference_id": 1, "quantity": 1},
                "reasoning": "x",
                "sneaky": "extra",
            }
        )


def test_the_default_selector_cannot_diverge_from_the_optimizer(session_factory):
    agent = RecoveryAgent(Toolbox(_seeded(session_factory)))
    assert isinstance(agent.selector, TopRankedSelector)
    run = agent.run()
    assert run.outcome is AgentOutcome.RESOLVED


# --- guardrail: bounded autonomy ------------------------------------------


def test_per_cycle_tool_call_budget_stops_the_run(session_factory, monkeypatch):
    monkeypatch.setattr("app.agent.loop.MAX_TOOL_CALLS_PER_CYCLE", 4)

    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    assert run.outcome is AgentOutcome.TOOL_CALL_LIMIT_REACHED
    # Three observe calls, then exactly the four the cycle was allowed before the
    # budget stopped it (three investigate + optimize).
    assert run.tool_calls == 3 + 4
    assert run.actions == []  # stopped before any stock-moving tool ran
    guardrails = [s for s in run.trace.steps if s.phase is AgentPhase.GUARDRAIL]
    assert any("tool-call budget" in (step.note or "") for step in guardrails)


def test_the_budget_is_generous_enough_for_a_normal_cycle(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    assert MAX_TOOL_CALLS_PER_CYCLE == 15
    assert run.tool_calls < MAX_TOOL_CALLS_PER_CYCLE


def test_replan_cap_stops_the_loop(session_factory):
    """(c) The hard replan cap really stops the loop."""
    toolbox = ScriptedToolbox(
        _seeded(session_factory), verify_script=[False, False, False]
    )
    run = RecoveryAgent(toolbox, max_replans=1).run()

    assert run.outcome is AgentOutcome.REPLAN_LIMIT_REACHED
    assert run.replan_cycles == 2  # two attempts, then the cap refuses a third
    assert len(run.actions) == 2
    assert [step.phase for step in run.trace.steps].count(AgentPhase.OPTIMIZE) == 2


def test_replans_after_a_failed_verification_then_resolves(session_factory):
    toolbox = ScriptedToolbox(_seeded(session_factory), verify_script=[False])
    run = RecoveryAgent(toolbox, max_replans=5).run()

    assert run.outcome is AgentOutcome.RESOLVED
    assert run.replan_cycles == 1
    tool_names = [action["tool"] for action in run.actions]
    # First cycle: reroute_shipment (top-ranked). Second cycle: vendor_purchase
    # (reroute already executed, so a different top option is chosen).
    assert tool_names[0] == "reroute_shipment"
    assert [step.phase for step in run.trace.steps].count(AgentPhase.OPTIMIZE) == 2


def test_max_replans_above_the_cap_is_clamped(session_factory):
    toolbox = ScriptedToolbox(_seeded(session_factory), verify_script=[False] * 10)
    agent = RecoveryAgent(toolbox, max_replans=99)

    assert agent.max_replans == 5  # clamped, not honoured

    run = agent.run()
    assert run.replan_cycles <= agent.max_replans + 1  # cap + the cycle that trips it
    assert run.outcome in {
        AgentOutcome.REPLAN_LIMIT_REACHED,
        AgentOutcome.NO_FEASIBLE_OPTION,
        AgentOutcome.ACTION_REJECTED,
    }


def test_a_refused_action_is_not_repeated(session_factory):
    # In the disrupted scenario the top option is reroute_shipment, not a purchase.
    # ScriptedToolbox.fail_purchase only blocks purchases; reroute succeeds and
    # resolves the run. To test the refused-action path we need a scenario where
    # a purchase is the top option: disable all routes so reroute is excluded.
    db = _seeded(session_factory)
    from app.models import Route
    for route in db.query(Route).all():
        route.is_available = False
    db.commit()

    toolbox = ScriptedToolbox(db, fail_purchase=True)
    run = RecoveryAgent(toolbox, max_replans=5).run()

    assert run.outcome is AgentOutcome.ACTION_REJECTED
    assert len(run.actions) >= 1
    assert run.actions[0]["ok"] is False
    assert run.actions[0]["reason"] == "vendor_unavailable"
    assert "refused" in run.explanation


# --- the trace ------------------------------------------------------------


def test_trace_records_arguments_and_raw_results(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    by_tool = {step.tool: step for step in run.trace.steps if step.tool}

    optimize = by_tool["optimize_recovery"]
    assert optimize.arguments == {
        "shortage_quantity": run.demand["shortage"],
        "deadline": run.demand["deadline"],
    }
    # Top option is reroute_shipment #1 via route #4: 620 km * 30 = 18600, 11 h.
    assert optimize.result["options"][0]["total_cost"] == 18600.0
    assert optimize.result["options"][0]["total_delivery_hours"] == 11.0
    assert optimize.result["options"][0]["action"] == "reroute_shipment"

    reroute = by_tool["reroute_shipment"]
    assert reroute.arguments["shipment_id"] == 1
    assert reroute.arguments["new_route_id"] == 4

    assert by_tool["verify_state"].result["satisfied"] is True
    assert [step.index for step in run.trace.steps] == list(range(len(run.trace.steps)))

    decide = next(step for step in run.trace.steps if step.phase is AgentPhase.DECIDE)
    assert decide.result["action"] == "reroute_shipment"
    assert decide.result["params"]["reference_id"] == 1
    assert decide.result["params"]["quantity"] == 700
    assert decide.result["reasoning"]


# --- guardrail: grounding -------------------------------------------------


def test_explanation_quotes_real_numbers_and_invents_none(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    # Top action is reroute_shipment; the explanation must quote its cost.
    assert "18600.0" in run.explanation
    assert ungrounded_numbers(run.explanation, run.trace) == []
    # The default explainer is itself the template, so no fallback was needed.
    assert run.grounding.attempts == 1
    assert run.grounding.rejected_numbers == []
    assert run.grounding.regenerated is False
    assert run.grounding.fallback_used is False


def test_template_separates_coverage_from_the_raw_on_hand_shortfall(session_factory):
    """A raw stock statistic must not sound like an unresolved recovery."""
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    summary = TemplateExplainer().explain(_context_from(run))

    assert summary.startswith("The requirement is now covered:")
    # The same raw 700-unit gap must never be framed as both resolved/covered
    # and remaining in one unqualified sentence.
    contradictory = re.compile(r"(?i)(?:shortfall|shortage).*700.*\bremains\b")
    assert not any(
        contradictory.search(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", summary)
    )


def test_an_invented_number_is_caught_and_the_explanation_regenerated(session_factory):
    """(b) A mismatched LLM figure is caught and the response regenerated."""
    explainer = RetryingExplainer()
    run = RecoveryAgent(
        Toolbox(_seeded(session_factory)), explainer=explainer
    ).run()

    # First draft, then a re-ask carrying the explicit instruction.
    assert explainer.corrections == [None, GROUNDING_INSTRUCTION]
    assert GROUNDING_INSTRUCTION == (
        "Only state numbers that appear in the tool results below. "
        "Do not estimate or infer any figures."
    )

    # The invented figures never reach the user; the regenerated text does.
    assert "424242" not in run.explanation
    assert "999999" not in run.explanation
    assert run.explanation == "Shortage stands at 700 units."

    assert run.grounding.attempts == 2
    assert run.grounding.rejected_numbers == [["424242", "999999"]]
    assert run.grounding.regenerated is True
    assert run.grounding.fallback_used is False
    assert ungrounded_numbers(run.explanation, run.trace) == []


def test_a_persistently_lying_explainer_falls_back_to_the_template(session_factory):
    class AlwaysWrong:
        def explain(self, context, *, correction=None):
            return "I bought 424242 bags."

    run = RecoveryAgent(
        Toolbox(_seeded(session_factory)), explainer=AlwaysWrong()
    ).run()

    assert "424242" not in run.explanation
    assert run.grounding.attempts == 2
    assert run.grounding.rejected_numbers == [["424242"], ["424242"]]
    assert run.grounding.fallback_used is True
    # Rejected twice for grounding, not for infrastructure: no reason to report.
    assert run.grounding.fallback_reason is None
    assert ungrounded_numbers(run.explanation, run.trace) == []


def test_an_unavailable_explainer_falls_back_without_being_asked_twice(session_factory):
    explainer = BrokenExplainer()
    run = RecoveryAgent(
        Toolbox(_seeded(session_factory)), explainer=explainer
    ).run()

    assert explainer.calls == 1  # infrastructure failure, not a grounding failure
    assert run.grounding.attempts == 1
    assert run.grounding.fallback_used is True
    # A fallback is never silent: the reason travels with the run.
    assert run.grounding.fallback_reason == "no api key"

    expected = TemplateExplainer().explain(
        ExplanationContext(
            outcome=run.outcome,
            demand=run.demand,
            plan=run.plan,
            verify=run.verify,
            actions=run.actions,
            replan_cycles=run.replan_cycles,
            trace=run.trace,
        )
    )
    assert run.explanation == expected
    # Top action is reroute; the template must quote its cost, not a vendor name.
    assert "18600.0" in run.explanation


def test_ungrounded_numbers_detects_an_invented_figure(session_factory):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    assert ungrounded_numbers(
        "The dealer needs 424242 units and it will cost 31337.5.", run.trace
    ) == ["424242", "31337.5"]
    assert ungrounded_numbers("Shortage of 700 units.", run.trace) == []


def test_ungrounded_numbers_helper_ignores_non_numeric_text():
    trace = ReasoningTrace()
    trace.add(AgentPhase.DETECT, note="nothing numeric here")
    assert ungrounded_numbers("no digits at all", trace) == []
    assert ungrounded_numbers("Value 5.", trace) == ["5"]


# --- agent actions are audited as the agent -------------------------------


def test_executed_actions_are_audited_with_the_agent_actor(seeded_client):
    seeded_client.post("/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 60})
    run = seeded_client.post("/agent/recover").json()

    logs = seeded_client.get("/audit-logs", params={"actor": "agent"}).json()
    action_types = {log["action_type"] for log in logs}
    # Top option is reroute_shipment in the disrupted scenario.
    assert "shipment_reroute" in action_types
    assert "agent_recovery_run" in action_types

    summary = next(log for log in logs if log["action_type"] == "agent_recovery_run")
    assert summary["result"] == "resolved"
    assert summary["details"]["run_id"] == run["run_id"]
    assert summary["details"]["satisfied"] is True
    assert summary["details"]["tool_calls"] == run["tool_calls"]
    assert summary["details"]["grounding"]["fallback_used"] is False

    assert run["audit_log_ids"] == sorted(run["audit_log_ids"])


# --- HTTP contract --------------------------------------------------------


def test_agent_tools_endpoint_lists_every_tool(seeded_client):
    tools = seeded_client.get("/agent/tools").json()
    assert [tool["name"] for tool in tools] == list(TOOL_SPECS)
    assert len(tools) == 10
    assert all(tool["endpoint"] and tool["description"] for tool in tools)


def test_recover_endpoint_returns_explanation_plan_trace_and_grounding(seeded_client):
    seeded_client.post("/simulate/shipment-delay", json={"shipment_id": 1, "delay_hours": 60})
    response = seeded_client.post("/agent/recover")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["outcome"] == "resolved"
    assert body["explanation"]
    assert body["verify"]["satisfied"] is True
    # Top option is reroute_shipment #1 (cheaper and faster than vendor_purchase).
    assert body["plan"]["options"][0]["reference_id"] == 1
    assert body["plan"]["options"][0]["action"] == "reroute_shipment"
    assert body["observed_demand"]["shortage"] == 700
    assert body["replan_cycles"] == 0
    assert body["tool_calls"] > 0
    assert body["grounding"] == {
        "attempts": 1,
        "rejected_numbers": [],
        "regenerated": False,
        "fallback_used": False,
        "fallback_reason": None,
    }
    assert [step["phase"] for step in body["trace"]][:1] == ["observe"]


def test_recover_endpoint_reports_no_action_needed(seeded_client):
    seeded_client.patch("/dealers/201", json={"required_quantity": 300})
    body = seeded_client.post("/agent/recover").json()

    assert body["outcome"] == "no_action_needed"
    assert body["actions"] == []
    assert body["verify"] is None


def test_recover_endpoint_is_typed_and_caps_replans(seeded_client):
    spec = seeded_client.get("/openapi.json").json()
    post = spec["paths"]["/agent/recover"]["post"]
    content = post["responses"]["200"]["content"]["application/json"]
    assert content["schema"]["$ref"].endswith("AgentRunResponse")

    too_many = seeded_client.post("/agent/recover", json={"max_replans": 99})
    assert too_many.status_code == 422
    assert seeded_client.post("/agent/recover", json={"max_replans": 0}).status_code == 200


# --- the Groq explainer (the only provider-specific code) ------------------


def _context_from(run) -> ExplanationContext:
    return ExplanationContext(
        outcome=run.outcome,
        demand=run.demand,
        plan=run.plan,
        verify=run.verify,
        actions=run.actions,
        replan_cycles=run.replan_cycles,
        trace=run.trace,
    )


def _install_stub_groq(monkeypatch, reply):
    """Swap the ``groq`` SDK for a stub; returns the clients it was asked for.

    ``reply`` is the content to answer with, or a callable taking the request
    kwargs. Keeps the provider tests offline and deterministic.
    """
    created = []

    class FakeGroq:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs):
            self.request = kwargs
            content = reply(kwargs) if callable(reply) else reply
            message = SimpleNamespace(content=content)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    module = ModuleType("groq")
    module.Groq = FakeGroq
    monkeypatch.setitem(sys.modules, "groq", module)
    return created


def test_the_groq_explainer_sends_the_trace_and_honours_the_correction(
    session_factory, monkeypatch
):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    clients = _install_stub_groq(monkeypatch, reply="Grounded summary.")
    explainer = GroqExplainer(
        api_key="gsk_test", model="openai/gpt-oss-120b", timeout=5, max_tokens=1234
    )

    text = explainer.explain(_context_from(run), correction=GROUNDING_INSTRUCTION)

    assert text == "Grounded summary."
    client = clients[0]
    assert client.kwargs == {"api_key": "gsk_test", "timeout": 5}
    request = client.request
    assert request["model"] == "openai/gpt-oss-120b"
    assert request["max_tokens"] == 1234  # must clear the reasoning burn
    assert request["extra_body"] == {"reasoning_effort": "low"}  # keeps a demo quick
    assert "temperature" not in request  # no provider-specific sampling tuning
    system, user = (message["content"] for message in request["messages"])
    assert "ONLY the numbers" in system
    assert GROUNDING_INSTRUCTION in system
    # The model is handed the numbers the tools already returned, verbatim.
    assert '"shortage": 700' in user
    assert '"total_cost": 255500.0' in user


def test_the_groq_explainer_raises_on_a_blank_reply(session_factory, monkeypatch):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    _install_stub_groq(monkeypatch, reply="   ")

    with pytest.raises(ExplainerUnavailable):
        GroqExplainer(api_key="gsk_test", model="m").explain(_context_from(run))


def test_the_groq_explainer_wraps_a_transport_failure(session_factory, monkeypatch):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    def boom(_request):
        raise RuntimeError("connection reset by peer")

    _install_stub_groq(monkeypatch, reply=boom)

    with pytest.raises(ExplainerUnavailable):
        GroqExplainer(api_key="gsk_test", model="m").explain(_context_from(run))


def test_reasoning_effort_can_be_switched_off(session_factory, monkeypatch):
    """Non-reasoning models reject the field, so an empty setting must omit it."""
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    clients = _install_stub_groq(monkeypatch, reply="Grounded.")

    GroqExplainer(
        api_key="gsk_test", model="llama-3.1-8b-instant", reasoning_effort=""
    ).explain(_context_from(run))

    assert "extra_body" not in clients[0].request


def test_the_groq_explainer_reports_a_missing_sdk(session_factory, monkeypatch):
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()
    monkeypatch.setitem(sys.modules, "groq", None)  # as if it were not installed

    with pytest.raises(ExplainerUnavailable):
        GroqExplainer(api_key="gsk_test", model="m").explain(_context_from(run))


def test_a_groq_backed_run_is_still_grounded_end_to_end(session_factory, monkeypatch):
    """The loop enforces grounding on model prose, not just on the template."""

    def answer_from_the_payload(request):
        # What a well-behaved model does: quote the JSON it was handed.
        payload = json.loads(request["messages"][1]["content"])
        top = payload["plan"]["options"][0]
        return f"Rerouted shipment {top['reference_id']} at cost {top['total_cost']}."

    _install_stub_groq(monkeypatch, reply=answer_from_the_payload)
    run = RecoveryAgent(
        Toolbox(_seeded(session_factory)),
        explainer=GroqExplainer(api_key="gsk_test", model="openai/gpt-oss-120b"),
    ).run()

    # Top option is reroute_shipment #1 via route #4: cost 18600.0.
    assert run.explanation == "Rerouted shipment 1 at cost 18600.0."
    assert run.grounding.attempts == 1
    assert run.grounding.regenerated is False
    assert run.grounding.fallback_used is False
    assert run.grounding.fallback_reason is None
    assert ungrounded_numbers(run.explanation, run.trace) == []


def test_the_groq_explainer_names_an_exhausted_token_budget(session_factory, monkeypatch):
    """A reasoning model bills its thinking to the same budget as its answer.

    The reply arrives empty with ``finish_reason=length``; that must be reported
    as a budget problem rather than as an unexplained "no text".
    """
    run = RecoveryAgent(Toolbox(_seeded(session_factory))).run()

    class ExhaustedGroq:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **_kwargs):
            usage = SimpleNamespace(completion_tokens_details={"reasoning_tokens": 698})
            choice = SimpleNamespace(
                finish_reason="length", message=SimpleNamespace(content="")
            )
            return SimpleNamespace(choices=[choice], usage=usage)

    module = ModuleType("groq")
    module.Groq = ExhaustedGroq
    monkeypatch.setitem(sys.modules, "groq", module)

    explainer = GroqExplainer(api_key="gsk_test", model="openai/gpt-oss-120b", max_tokens=700)
    with pytest.raises(ExplainerUnavailable, match="AGENT_EXPLAINER_MAX_TOKENS"):
        explainer.explain(_context_from(run))

    with pytest.raises(ExplainerUnavailable, match="698 on reasoning"):
        explainer.explain(_context_from(run))


def test_an_exhausted_budget_explains_the_template_fallback(seeded_client, monkeypatch):
    """End to end: the run falls back *and* says why."""
    import app.agent.loop as loop_module

    class Broken:
        def explain(self, context, *, correction=None):
            raise ExplainerUnavailable(
                "LLM explainer used its whole 700 token budget (698 on reasoning) "
                "before writing any text; raise AGENT_EXPLAINER_MAX_TOKENS"
            )

    monkeypatch.setattr(loop_module, "choose_explainer", lambda: Broken())
    body = seeded_client.post("/agent/recover").json()

    assert body["grounding"]["fallback_used"] is True
    assert "AGENT_EXPLAINER_MAX_TOKENS" in body["grounding"]["fallback_reason"]
    assert body["explanation"]  # the template still produced a grounded summary


def test_choose_explainer_uses_groq_only_when_a_key_is_configured(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(groq_api_key=None))
    assert isinstance(choose_explainer(), TemplateExplainer)

    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: Settings(
            groq_api_key="gsk_from_the_environment",
            agent_explainer_model="openai/gpt-oss-120b",
            agent_explainer_timeout=7,
            agent_explainer_max_tokens=4096,
        ),
    )
    chosen = choose_explainer()
    assert isinstance(chosen, GroqExplainer)
    assert chosen.api_key == "gsk_from_the_environment"
    assert chosen.model == "openai/gpt-oss-120b"
    assert chosen.timeout == 7
    assert chosen.max_tokens == 4096
