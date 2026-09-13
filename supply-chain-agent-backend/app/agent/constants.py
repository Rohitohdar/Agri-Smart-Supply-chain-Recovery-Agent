"""Constants shared by the agent loop, its guardrails and the request schemas.

Kept in a leaf module (no imports) so the schema layer can reference the caps
without importing the loop, which would form an import cycle.
"""

#: Hard cap on replan cycles. A caller may lower it, never raise it.
MAX_REPLAN_CYCLES = 5

#: Hard cap on tool calls inside a single reasoning cycle, so a cycle can never
#: run away (a normal cycle uses six: three investigate, optimize, execute, verify).
MAX_TOOL_CALLS_PER_CYCLE = 15

#: Reported verbatim when the optimizer finds nothing feasible. Kept as a
#: constant so the honest refusal is an explicit code path, not a paraphrase an
#: LLM might soften into a guess.
NO_FEASIBLE_MESSAGE = "No feasible recovery option meets the current constraints"

#: Sent back to the explainer when its first attempt cites an untraceable number.
GROUNDING_INSTRUCTION = (
    "Only state numbers that appear in the tool results below. "
    "Do not estimate or infer any figures."
)
