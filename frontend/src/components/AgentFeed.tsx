import { useEffect, useRef } from "react";

import { errorMessage, isMissingApiKey, isRateLimited, isUnauthorized } from "../api/client";
import type { AgentRun } from "../api/types";
import { OUTCOME_META, type Narrative } from "../lib/describe";
import { formatNumber } from "../lib/format";
import type { RunStatus } from "../state/useAgentRun";
import { JsonDetails } from "./JsonDetails";
import { StatusPill } from "./StatusPill";

const PHASES = ["observe", "detect", "investigate", "optimize", "decide", "execute", "verify"] as const;
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

function PhaseStepper({ currentPhase }: { currentPhase: string | null }) {
  return (
    <div className="stepper" role="list" aria-label="Agent reasoning phases">
      {PHASES.map((phase, i) => {
        const phaseIndex = PHASES.indexOf(phase as typeof PHASES[number]);
        const currentIndex = currentPhase ? PHASES.indexOf(currentPhase as typeof PHASES[number]) : -1;
        const isDone = currentIndex > phaseIndex;
        const isActive = currentPhase === phase || (currentIndex === -1 && i === 0);
        return (
          <div key={phase} className="stepper__step" role="listitem">
            {i > 0 && <span className="stepper__arrow" aria-hidden="true">›</span>}
            <span
              className={`stepper__label${isActive ? " stepper__label--active" : isDone ? " stepper__label--done" : ""}`}
              aria-current={isActive ? "step" : undefined}
            >
              {PHASE_LABELS[phase]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function FirstRunGuide() {
  return (
    <div className="guide">
      <p className="muted">Follow these three steps to run a demo:</p>
      <div className="guide__steps">
        <div className="guide__step">
          <div className="guide__num" aria-hidden="true">1</div>
          <div className="guide__text">
            <strong>Reset scenario</strong>
            <span>Use the Connection panel to restore the seeded starting state.</span>
          </div>
        </div>
        <div className="guide__step">
          <div className="guide__num" aria-hidden="true">2</div>
          <div className="guide__text">
            <strong>Inject a disruption</strong>
            <span>Delay a shipment, block a route, or disable a vendor below.</span>
          </div>
        </div>
        <div className="guide__step">
          <div className="guide__num" aria-hidden="true">3</div>
          <div className="guide__text">
            <strong>Run recovery</strong>
            <span>Press the button above — the agent will observe, decide, and act.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AgentFeed({
  run,
  narratives,
  status,
  error,
  revealedCount,
  canRun,
  blockedReason,
  hasEverRun,
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
  hasEverRun: boolean;
  onRun: () => void;
  onSkip: () => void;
  onClear: () => void;
}) {
  const logRef = useRef<HTMLDivElement | null>(null);
  const running = status === "running";
  const revealing = status === "done" && run !== null && revealedCount < run.trace.length;
  const visible = narratives.slice(0, revealedCount);
  const traceByIndex = new Map((run?.trace ?? []).map((step) => [step.index, step]));

  // Current phase: the last revealed step's phase while revealing, or null while running
  const currentPhase = running
    ? (visible.at(-1)?.phase ?? null)
    : null;

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
            aria-label={running ? "Agent is working" : "Run recovery agent"}
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
            <button
              type="button"
              className="button button--ghost"
              aria-label="Clear agent run results"
              onClick={onClear}
            >
              Clear
            </button>
          ) : null}
        </div>
      </header>

      {blockedReason ? <p className="notice notice--warn">{blockedReason}</p> : null}

      {/* First-run guide — only shown before any run has ever been attempted */}
      {status === "idle" && !hasEverRun ? <FirstRunGuide /> : null}

      {/* Idle state after a clear */}
      {status === "idle" && hasEverRun ? (
        <div className="empty">
          <p>
            <strong>Run recovery</strong> asks the agent to look at the current state and fix a
            violation if there is one. It reasons in six steps — observe, detect, investigate,
            optimize, execute, verify — and every tool call it makes will appear here in plain
            language, with the raw response behind <em>view details</em>.
          </p>
        </div>
      ) : null}

      {/* Phase stepper — shown while the request is in flight */}
      {running ? (
        <div>
          <PhaseStepper currentPhase={currentPhase} />
          <p className="feed-status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            Agent is reasoning — results will appear when complete…
          </p>
        </div>
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
