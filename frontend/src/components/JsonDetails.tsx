import { useId, useState } from "react";

/**
 * The "view details" toggle.
 *
 * The console's default voice is plain language, because the person judging this
 * may not read JSON. Nothing is hidden, though: every claim the plain-language
 * view makes can be expanded to the exact payload the backend returned, which is
 * what a technical reviewer needs to verify it.
 */
export function JsonDetails({
  label = "view details",
  value,
  summary,
}: {
  label?: string;
  value: unknown;
  summary?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? "null";
  } catch {
    text = String(value);
  }

  return (
    <div className="details">
      <button
        type="button"
        className="details__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((previous) => !previous)}
      >
        <span className="details__chevron" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        {open ? "hide details" : label}
        {summary ? <span className="details__summary">{summary}</span> : null}
      </button>
      {open ? (
        <pre className="details__panel" id={panelId}>
          {text}
        </pre>
      ) : null}
    </div>
  );
}
