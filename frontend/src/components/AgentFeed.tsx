import { useEffect, useRef } from "react";

import { errorMessage, isMissingApiKey, isRateLimited, isUnauthorized } from "../api/client";
import type { AgentRun } from "../api/types";
import { OUTCOME_META, type Narrative } from "../lib/describe";
import { formatNumber } from "../lib/format";
import type { RunStatus } from "../state/useAgentRun";
import { JsonDetails } from "./JsonDetails";
import { StatusPill } from "./StatusPill";

const PHASE_LABELS: Record<string, string> = {
  observe: "OBSERVE",
  detect: "DETECT",
  investigate: "INVESTIGATE",
  optimize: "OPTIMIZE",
  decide: "DECIDE",
  execute: "EXECUTE",
  verify: "VERIFY",
  guardrail: "GUARDRAIL",
};

export function AgentFeed({
  run,
  narratives,
  status,
  error,
  revealedCount,
  canRun,
  blockedReason,
  onRun,
  onSkip,
  onClear,
}: {
  run: AgentRun | null;
  narratives: Narrative[];
  status: RunStatus;
  error: unknown;
  revealedCount: number;
  canRun: boolean;
  blockedReason: string | null;
  onRun: () => void;
  onSkip: () => void;
  onClear: () => void;
}) {
  const logRef = useRef<HTMLDivElement | null>(null);
  const running = status === "running";
  const revealing = status === "done" && run !== null && revealedCount < run.trace.length;
  const visible = narratives.slice(0, revealedCount);
  // Keyed by the step's own index rather than by array position, so a trace that
  // ever arrives out of order still pairs each sentence with its own payload.
  const traceByIndex = new Map((run?.trace ?? []).map((step) => [step.index, step]));

  // Follow the newest step, like a log tail.
  useEffect(() => {
    const node = logRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [revealedCount, running]);

  return (
    <section className="card card--wide" aria-labelledby="feed-heading">
      <header className="card__header">
        <h2 id="feed-heading">Agent activity</h2>
        <div className="card__header-meta">
          {run ? (
            <StatusPill tone={OUTCOME_META[run.outcome].tone}>
              {OUTCOME_META[run.outcome].label}
            </StatusPill>
          ) : null}
          <button
            type="button"
            className="button button--primary"
            disabled={!canRun || running}
            title={blockedReason ?? "Observe, decide, act, verify — one pass"}
            onClick={onRun}
          >
            {running ? "Agent working…" : "Run recovery"}
          </button>
          {revealing ? (
            <button type="button" className="button button--ghost" onClick={onSkip}>
              Skip
            </button>
          ) : null}
          {run || error ? (
            <button type="button" className="button button--ghost" onClick={onClear}>
              Clear
            </button>
          ) : null}
        </div>
      </header>

      {blockedReason ? <p className="notice notice--warn">{blockedReason}</p> : null}

      {status === "idle" ? (
        <div className="empty">
          <p>
            <strong>Run recovery</strong> asks the agent to look at the current state and fix a
            violation if there is one. It reasons in six steps — observe, detect, investigate,
            optimize, execute, verify — and every tool call it makes will appear here in plain
            language, with the raw response behind <em>view details</em>.
          </p>
          <p className="muted">
            The agent never computes cost, delivery or carbon itself, and cannot invent a number:
            those come from the optimizer, and its closing summary is checked against the tool
            results before you see it.
          </p>
        </div>
      ) : null}

      {running ? (
        <p className="feed-status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          Agent is observing the system and reasoning about a response…
        </p>
      ) : null}

      {status === "error" ? (
        <p className="notice notice--danger">{describeRunError(error)}</p>
      ) : null}

      <div className="feed" ref={logRef} aria-live="polite">
        {visible.map((step) => {
          const traceStep = traceByIndex.get(step.index);
          return (
            <article key={step.index} className={`feed__row feed__row--${step.tone}`}>
              <div className="feed__rail" aria-hidden="true" />
              <div className="feed__body">
                <div className="feed__head">
                  <span className="feed__phase">{PHASE_LABELS[step.phase] ?? step.phase}</span>
                  {step.isAction ? (
                    <span className="badge badge--info" title="This step changed state">
                      changed state
                    </span>
                  ) : null}
                  <h3 className="feed__title">{step.title}</h3>
                </div>
                {step.detail ? <p className="feed__detail">{step.detail}</p> : null}
                {traceStep ? (
                  <JsonDetails
                    label="view tool call"
                    value={{
                      tool: traceStep.tool,
                      arguments: traceStep.arguments,
                      result: traceStep.result,
                      note: traceStep.note,
                    }}
                  />
                ) : null}
              </div>
            </article>
          );
        })}

        {revealing ? (
          <p className="feed-status">
            <span className="spinner" aria-hidden="true" />
            {formatNumber(run ? run.trace.length - revealedCount : 0)} more step(s)…
          </p>
        ) : null}

        {status === "done" && run && !revealing ? (
          <p className={`notice notice--${OUTCOME_META[run.outcome].tone}`}>
            <strong>{OUTCOME_META[run.outcome].label}.</strong> {OUTCOME_META[run.outcome].blurb}
          </p>
        ) : null}
      </div>
    </section>
  );
}

function describeRunError(error: unknown): string {
  if (isMissingApiKey(error)) {
    return "Enter the API key in the Connection panel, then run the agent again.";
  }
  if (isUnauthorized(error)) {
    return "The backend rejected the API key, so the agent was never started. Check the key in the Connection panel.";
  }
  if (isRateLimited(error)) {
    return errorMessage(error);
  }
  return errorMessage(error);
}
