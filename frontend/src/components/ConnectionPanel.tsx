import { useState } from "react";

import { API_KEY_HEADER } from "../api/client";
import type { HealthResponse } from "../api/types";
import { StatusPill } from "./StatusPill";

export interface Controls {
  baseUrl: string;
  apiKey: string;
  intervalMs: number;
}

const INTERVALS: Array<{ label: string; value: number }> = [
  { label: "every 2 s", value: 2000 },
  { label: "every 4 s", value: 4000 },
  { label: "every 10 s", value: 10_000 },
  { label: "paused", value: 0 },
];

export function ConnectionPanel({
  controls,
  onControlsChange,
  health,
  healthError,
  lastUpdatedAt,
  onReset,
  resetting,
}: {
  controls: Controls;
  onControlsChange: (next: Partial<Controls>) => void;
  health: HealthResponse | null;
  healthError: unknown;
  lastUpdatedAt: Date | null;
  onReset: () => void;
  resetting: boolean;
}) {
  const [showKey, setShowKey] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  const connected = health !== null && healthError === null;
  const writesAuthenticated = health?.writes_authenticated ?? false;
  const hasKey = controls.apiKey.trim().length > 0;

  return (
    <section className="card" aria-labelledby="connection-heading">
      <header className="card__header">
        <h2 id="connection-heading">Connection</h2>
        <StatusPill tone={connected ? "ok" : "danger"}>
          {connected ? "Backend reachable" : "Backend unreachable"}
        </StatusPill>
      </header>

      <div className="field">
        <label htmlFor="base-url">Backend URL</label>
        <input
          id="base-url"
          type="url"
          value={controls.baseUrl}
          spellCheck={false}
          onChange={(event) => onControlsChange({ baseUrl: event.target.value })}
        />
      </div>

      <div className="field">
        <label htmlFor="api-key">
          API key <code>{API_KEY_HEADER}</code>
        </label>
        <div className="field__row">
          <input
            id="api-key"
            type={showKey ? "text" : "password"}
            value={controls.apiKey}
            autoComplete="off"
            spellCheck={false}
            placeholder="from the backend's API_KEY setting"
            onChange={(event) => onControlsChange({ apiKey: event.target.value })}
          />
          <button type="button" className="button button--ghost" onClick={() => setShowKey((v) => !v)}>
            {showKey ? "Hide" : "Show"}
          </button>
        </div>
        <p className="field__hint">
          Kept in this browser only and sent as the <code>{API_KEY_HEADER}</code> header.
          Every button that changes state goes through it — the console will not
          call an action endpoint without it.
        </p>
      </div>

      <div className="field">
        <label htmlFor="interval">Refresh</label>
        <select
          id="interval"
          value={controls.intervalMs}
          onChange={(event) => onControlsChange({ intervalMs: Number(event.target.value) })}
        >
          {INTERVALS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="field__hint">
          Fetches five endpoints per tick (about 75 requests/minute at 4 s), inside the
          backend&apos;s default 200/minute limit. Polling pauses while this tab is hidden.
        </p>
      </div>

      <dl className="facts">
        <div>
          <dt>Environment</dt>
          <dd>{health?.environment ?? "—"}</dd>
        </div>
        <div>
          <dt>Writes</dt>
          <dd>
            {writesAuthenticated ? (
              <StatusPill tone={hasKey ? "ok" : "warn"}>
                {hasKey ? "Authenticated" : "Key required"}
              </StatusPill>
            ) : (
              <StatusPill tone="warn" title="The backend has no API_KEY set, so it accepts writes from anything that can reach it. Fine on localhost; set API_KEY before exposing it.">
                Open — no key set
              </StatusPill>
            )}
          </dd>
        </div>
        <div>
          <dt>Last updated</dt>
          <dd>{lastUpdatedAt ? lastUpdatedAt.toLocaleTimeString() : "—"}</dd>
        </div>
      </dl>

      {!writesAuthenticated && connected ? (
        <p className="notice notice--warn">
          The backend is running in development demo mode: it accepts changes without a key.
          Set <code>API_KEY</code> on the backend and enter it here to require authentication.
        </p>
      ) : null}

      <div className="card__actions">
        {confirmingReset ? (
          <>
            <button
              type="button"
              className="button button--danger"
              disabled={resetting}
              onClick={() => {
                onReset();
                setConfirmingReset(false);
              }}
            >
              {resetting ? "Resetting…" : "Confirm reset"}
            </button>
            <button type="button" className="button button--ghost" onClick={() => setConfirmingReset(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button type="button" className="button" onClick={() => setConfirmingReset(true)}>
            Reset scenario
          </button>
        )}
        <span className="card__note">Restores the seeded starting state.</span>
      </div>
    </section>
  );
}
