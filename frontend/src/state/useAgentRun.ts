/**
 * The agent run's lifecycle, in one place.
 *
 * The backend returns the whole reasoning trace in a single response — it has
 * no streaming endpoint — so the console cannot watch the agent think. What it
 * *can* do honestly is show the run as it happened: a spinner while the request
 * is in flight, then the recorded steps revealed in order once the answer
 * arrives. The steps, their order and their numbers are exactly the ones the
 * backend returned; only the timing of the reveal is the UI's. "Skip" jumps
 * straight to the full trace.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { runAgent } from "../api/client";
import type { AgentRun, Demand } from "../api/types";

export type RunStatus = "idle" | "running" | "done" | "error";

/** Milliseconds between revealed trace steps during the playback. */
const REVEAL_MS = 320;

export interface AgentRunState {
  status: RunStatus;
  run: AgentRun | null;
  error: unknown;
  /** Demand as it stood immediately before the run, for the before/after card. */
  before: Demand | null;
  /** How many trace steps have been revealed so far. */
  revealedCount: number;
}

const EMPTY: AgentRunState = {
  status: "idle",
  run: null,
  error: null,
  before: null,
  revealedCount: 0,
};

export interface AgentRunController {
  state: AgentRunState;
  start: (before: Demand | null, maxReplans?: number) => Promise<void>;
  revealAll: () => void;
  clear: () => void;
}

export function useAgentRun(): AgentRunController {
  const [state, setState] = useState<AgentRunState>(EMPTY);
  const abortRef = useRef<AbortController | null>(null);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(EMPTY);
  }, []);

  const start = useCallback(async (before: Demand | null, maxReplans?: number) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ status: "running", run: null, error: null, before, revealedCount: 0 });
    try {
      const run = await runAgent(maxReplans, controller.signal);
      if (controller.signal.aborted) return;
      setState({
        status: "done",
        run,
        error: null,
        before,
        // Reveal at least one step immediately so the feed is never blank.
        revealedCount: Math.min(1, run.trace.length),
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      setState({ status: "error", run: null, error, before, revealedCount: 0 });
    }
  }, []);

  const revealAll = useCallback(() => {
    setState((previous) =>
      previous.run
        ? { ...previous, revealedCount: previous.run.trace.length }
        : previous,
    );
  }, []);

  // Step the reveal forward until the whole trace is on screen.
  useEffect(() => {
    if (state.status !== "done" || !state.run) return;
    if (state.revealedCount >= state.run.trace.length) return;
    const timer = window.setTimeout(() => {
      setState((previous) =>
        previous.run
          ? {
              ...previous,
              revealedCount: Math.min(previous.revealedCount + 1, previous.run.trace.length),
            }
          : previous,
      );
    }, REVEAL_MS);
    return () => window.clearTimeout(timer);
  }, [state.status, state.run, state.revealedCount]);

  useEffect(() => () => abortRef.current?.abort(), []);

  return { state, start, revealAll, clear };
}

export function isRevealing(state: AgentRunState): boolean {
  return (
    state.status === "running" ||
    (state.status === "done" &&
      state.run !== null &&
      state.revealedCount < state.run.trace.length)
  );
}
