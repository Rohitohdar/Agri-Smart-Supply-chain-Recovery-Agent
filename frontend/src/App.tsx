import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  configureClient,
  errorMessage,
  getAuditTrail,
  getClientConfig,
  resetScenario,
} from "./api/client";
import { useHealth, useLocalStorage, usePolling, useSnapshot } from "./api/hooks";
import type { AuditEntry } from "./api/types";
import { AgentFeed } from "./components/AgentFeed";
import { BeforeAfterCard } from "./components/BeforeAfterCard";
import { ConnectionPanel, type Controls } from "./components/ConnectionPanel";
import { DisruptionPanel } from "./components/DisruptionPanel";
import { OutcomeCard } from "./components/OutcomeCard";
import { SystemStatusPanel } from "./components/SystemStatusPanel";
import { ArtDefs } from "./art/Defs";
import { describeTrace } from "./lib/describe";
import { countActive, deriveDisruptions, disruptionEntries } from "./lib/disruptions";
import { FieldHero } from "./sections/FieldHero";
import { NetworkPoster } from "./sections/NetworkPoster";
import { RecoveryHero, type DemoStep } from "./sections/RecoveryHero";
import { SiteFooter } from "./sections/SiteFooter";
import { isRevealing, useAgentRun } from "./state/useAgentRun";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

export function App() {
  const [controls, setControls] = useLocalStorage<Controls>("console.controls", {
    baseUrl: DEFAULT_BASE_URL,
    apiKey: "",
    intervalMs: 4000,
  });

  const hasKey = controls.apiKey.trim().length > 0;
  const pollMs = controls.intervalMs;

  const health = useHealth(10_000);
  const writesAuthenticated = health.data?.writes_authenticated ?? false;
  const snapshot = useSnapshot(pollMs);

  // The audit trail is gated by the backend, so it is only polled once there is
  // a way to authenticate. Waiting for `/health` matters: before it answers, the
  // auth policy is unknown, and polling anyway would earn a guaranteed 401 on
  // every page load.
  const auditEnabled =
    pollMs > 0 && health.data !== null && !(writesAuthenticated && !hasKey);
  const audit = usePolling<AuditEntry[]>(
    useCallback((signal) => getAuditTrail({ actionType: "disruption_injected", limit: 50 }, signal), []),
    Math.max(pollMs * 3, 9000),
    auditEnabled,
  );

  const agent = useAgentRun();
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  // Keep the client's configuration (and therefore its auth behaviour) in step.
  useEffect(() => {
    configureClient({ baseUrl: controls.baseUrl });
  }, [controls.baseUrl]);

  useEffect(() => {
    configureClient({ apiKey: controls.apiKey.trim() || null });
  }, [controls.apiKey]);

  useEffect(() => {
    if (health.data) configureClient({ writesAuthenticated: health.data.writes_authenticated });
  }, [health.data]);

  // A different backend means different data: re-read immediately, not on the
  // next tick, but skip the very first render (the mount effect already fetches).
  const initialised = useRef(false);
  useEffect(() => {
    if (!initialised.current) {
      initialised.current = true;
      return;
    }
    snapshot.refresh();
    health.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controls.baseUrl]);

  const onControlsChange = useCallback(
    (next: Partial<Controls>) => setControls({ ...controls, ...next }),
    [controls, setControls],
  );

  const onDisruptionChanged = useCallback(() => {
    snapshot.refresh();
    audit.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot.refresh, audit.refresh]);

  async function onReset() {
    setResetting(true);
    setResetError(null);
    try {
      await resetScenario();
      agent.clear();
    } catch (caught) {
      setResetError(errorMessage(caught));
    } finally {
      setResetting(false);
      snapshot.refresh();
      audit.refresh();
    }
  }

  const snapshotData = snapshot.data;
  const disruptions = useMemo(
    () =>
      snapshotData
        ? deriveDisruptions(disruptionEntries(audit.data ?? []), {
            demand: snapshotData.demand,
            shipments: snapshotData.shipments,
            routes: snapshotData.routes,
            vendors: snapshotData.vendors,
          })
        : [],
    [snapshotData, audit.data],
  );

  const narratives = useMemo(
    () => (agent.state.run ? describeTrace(agent.state.run.trace, agent.state.run.plan) : []),
    [agent.state.run],
  );

  const activeCount = countActive(disruptions);
  const reachable = snapshot.data !== null && snapshot.error === null;

  const blockedReason = useMemo(() => {
    if (health.error !== null) {
      return `Cannot reach the backend at ${getClientConfig().baseUrl}. Start it, check the URL above, and make sure CORS_ORIGINS includes ${window.location.origin}.`;
    }
    if (writesAuthenticated && !hasKey) {
      return "The backend requires an API key for changes. Enter it in the Connection panel to unlock the controls.";
    }
    return null;
  }, [health.error, writesAuthenticated, hasKey]);

  const overallTone = !reachable
    ? "danger"
    : snapshotData?.demand.constraint_violated
      ? "danger"
      : activeCount > 0
        ? "warn"
        : "ok";
  // "Disruption in effect" is reserved for a disruption that was actually
  // injected. The seeded scenario is short on its own, and calling that a
  // disruption would contradict the panel below it, which reports none injected.
  const overallLabel = !reachable
    ? "Disconnected"
    : activeCount > 0
      ? snapshotData?.demand.constraint_violated
        ? "Disruption in effect"
        : "Degraded"
      : snapshotData?.demand.constraint_violated
        ? "Constraint violated"
        : "Healthy";

  const heroSub = !reachable
    ? "Cannot reach the backend — check the URL in the Connection panel."
    : snapshotData?.demand.constraint_violated
      ? `${snapshotData.demand.dealer_name} is short by ${snapshotData.demand.on_hand_shortfall.toLocaleString()} units — the agent needs to act.`
      : activeCount > 0
        ? `${activeCount} disruption(s) injected — the system is degraded but the constraint is not yet violated.`
        : snapshotData
          ? `${snapshotData.demand.dealer_name} has enough supply arriving on time — no action needed.`
          : "Waiting for data…";

  const hasEverRun = agent.state.run !== null || agent.state.status !== "idle";

  const running = agent.state.status === "running";
  const demoStep: DemoStep = agent.state.run !== null ? 3 : activeCount > 0 ? 2 : 1;
  const liveText = pollMs === 0 ? "polling paused" : reachable ? "live feed" : "offline";
  const onRun = () => void agent.start(snapshotData?.demand ?? null);

  return (
    <div className="site">
      <ArtDefs />

      <FieldHero
        snapshot={snapshotData}
        reachable={reachable}
        tone={overallTone}
        label={overallLabel}
        sub={heroSub}
        liveText={liveText}
      />

      <main>
        {snapshot.error !== null ? (
          <p className="notice notice--danger page-notice">
            <strong>Cannot read the backend.</strong> {errorMessage(snapshot.error)}
          </p>
        ) : null}
        {resetError ? <p className="notice notice--danger page-notice">Reset failed: {resetError}</p> : null}

        <div className="paper-sheet">
          <NetworkPoster snapshot={snapshotData} tone={overallTone} />
          <SystemStatusPanel
            snapshot={snapshotData}
            disruptions={disruptions}
            disruptionsLoading={auditEnabled && audit.data === null && audit.error === null}
          />
        </div>

        <div className="kraft">
          <RecoveryHero
            step={demoStep}
            canRun={blockedReason === null}
            running={running}
            blockedReason={blockedReason}
            onRun={onRun}
          />

          <div className="kraft__body">
            <DisruptionPanel
              snapshot={snapshotData}
              blockedReason={blockedReason}
              onChanged={onDisruptionChanged}
            />

            <AgentFeed
              run={agent.state.run}
              narratives={narratives}
              status={agent.state.status}
              error={agent.state.error}
              revealedCount={agent.state.revealedCount}
              canRun={blockedReason === null}
              blockedReason={blockedReason}
              hasEverRun={hasEverRun}
              onRun={onRun}
              onSkip={agent.revealAll}
              onClear={agent.clear}
            />

            <div className="results">
              <BeforeAfterCard before={agent.state.before} run={agent.state.run} />
              <OutcomeCard run={agent.state.run} />
            </div>

            <ConnectionPanel
              controls={controls}
              onControlsChange={onControlsChange}
              health={health.data}
              healthError={health.error}
              lastUpdatedAt={snapshot.lastUpdatedAt}
              onReset={() => void onReset()}
              resetting={resetting}
            />
          </div>

          <SiteFooter>
            <p>
              Status is polled from <code>GET /demand</code>, <code>/shipments</code>,{" "}
              <code>/routes</code>, <code>/vendors</code> and <code>/inventory</code>. Controls call
              the <code>/simulate/*</code> endpoints and <code>POST /agent/recover</code>. Every
              state-changing call carries the API key and is validated, atomic and audited by the
              backend — the console cannot bypass that.
            </p>
            <p>
              {isRevealing(agent.state)
                ? "Revealing the recorded trace…"
                : "Trace steps are the ones the backend returned, shown in order."}{" "}
              Press <em>view details</em> anywhere to see the raw JSON behind a claim. Photographs
              from Unsplash.
            </p>
          </SiteFooter>
        </div>
      </main>
    </div>
  );
}
