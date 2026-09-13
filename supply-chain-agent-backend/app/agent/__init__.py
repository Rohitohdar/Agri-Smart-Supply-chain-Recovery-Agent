"""The supply-chain agent layer.

Orchestration and explanation only — the agent calls tools, records what they
return and narrates the result. All cost/delivery/carbon arithmetic lives in
``app.optimizer`` (via the ``optimize_recovery`` tool) and all validation lives
in ``app.services.action_service``.

The loop is a deliberate *custom* implementation rather than a model-driven
tool-use loop: the required step order and the hard replan cap are policy, not
something to leave to a model's discretion, and keeping them in code makes the
behaviour testable offline and provable. The LLM, when one is configured, is
confined to the final explanation, where its output is checked against the trace
before it is shown (see :mod:`app.agent.explain`).

This package marker deliberately imports nothing, so that leaf modules such as
``app.agent.trace`` and ``app.agent.constants`` can be imported from the schema
layer without dragging in the services (which would form an import cycle).

Entry points live in :mod:`app.agent.loop` (``RecoveryAgent``,
``run_recovery_agent``) and :mod:`app.agent.tools` (``Toolbox``,
``tool_catalogue``).
"""
