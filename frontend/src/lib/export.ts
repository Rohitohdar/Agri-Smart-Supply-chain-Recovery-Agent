/**
 * Audit report export (feature D).
 *
 * Serialises a completed AgentRun to a Markdown document and triggers a
 * browser download. No server round-trip — everything is already in the run
 * object the agent returned. The document is structured so it can be attached
 * to a ticket, printed, or committed as evidence.
 *
 * Only pure formatting happens here: no domain arithmetic, no API calls.
 */

import type { AgentRun } from "../api/types";
import { formatCarbon, formatCost, formatDateTime, formatHours, formatNumber } from "./format";

function line(text = ""): string {
  return text + "\n";
}

function section(title: string): string {
  return line(`## ${title}`) + line();
}

function row(...cells: string[]): string {
  return `| ${cells.join(" | ")} |`;
}

function tableHeader(...headers: string[]): string {
  return (
    row(...headers) +
    "\n" +
    row(...headers.map(() => "---"))
  );
}

export function buildAuditMarkdown(run: AgentRun): string {
  const lines: string[] = [];
  const now = new Date().toISOString();

  lines.push(line("# Supply Chain Recovery — Audit Report"));
  lines.push(line(`Generated: ${now}`));
  lines.push(line(`Run ID: \`${run.run_id}\``));
  lines.push(line(`Outcome: **${run.outcome}**`));
  lines.push(line());

  // --- Situation snapshot -------------------------------------------------
  lines.push(section("Situation at time of run"));
  const d = run.observed_demand;
  lines.push(line(`- Dealer: **${d.dealer_name}** (${d.location})`));
  lines.push(line(`- Required: **${formatNumber(d.required_quantity)} units** by ${formatDateTime(d.deadline)}`));
  lines.push(line(`- On hand: ${formatNumber(d.available_quantity)} units`));
  lines.push(line(`- On-hand shortfall: ${formatNumber(d.shortage)} units`));
  lines.push(line(`- Constraint violated: **${d.constraint_violated ? "Yes" : "No"}**`));
  if (d.constraint_violations.length > 0) {
    d.constraint_violations.forEach((v) => lines.push(line(`  - ${v}`)));
  }
  lines.push(line());

  // --- Recovery plan ------------------------------------------------------
  if (run.plan) {
    lines.push(section("Recovery plan — ranked options"));
    lines.push(line(tableHeader("Rank", "Option", "Action", "Cost", "Delivery", "Carbon", "Score")));
    for (const opt of run.plan.options) {
      lines.push(line(row(
        String(opt.rank),
        opt.label,
        opt.action,
        formatCost(opt.total_cost),
        formatHours(opt.total_delivery_hours),
        formatCarbon(opt.total_carbon),
        opt.single_feasible_option ? "only option" : opt.score.toFixed(4),
      )));
    }
    lines.push(line());

    if (run.plan.excluded.length > 0) {
      lines.push(line("### Ruled-out candidates"));
      lines.push(line(tableHeader("Option", "Action", "Reason", "Available qty", "Delivery", "Hours available")));
      for (const ex of run.plan.excluded) {
        lines.push(line(row(
          ex.label,
          ex.action,
          ex.reason,
          formatNumber(ex.available_quantity),
          formatHours(ex.delivery_hours ?? undefined),
          formatHours(ex.hours_available ?? undefined),
        )));
      }
      lines.push(line());
    }
  }

  // --- Actions taken -------------------------------------------------------
  lines.push(section("Actions executed"));
  if (run.actions.length === 0) {
    lines.push(line("No state-changing actions were taken."));
  } else {
    for (const action of run.actions) {
      const status = action.ok ? "✅ succeeded" : "❌ refused";
      lines.push(line(`- **${action.tool}** — ${status}`));
      lines.push(line(`  - Arguments: \`${JSON.stringify(action.arguments)}\``));
      if (!action.ok && action.error) {
        lines.push(line(`  - Error: ${action.error}${action.reason ? ` (${action.reason})` : ""}`));
      }
    }
  }
  lines.push(line());

  // --- Verification --------------------------------------------------------
  if (run.verify) {
    lines.push(section("Verification"));
    const v = run.verify;
    lines.push(line(`- Satisfied: **${v.satisfied ? "Yes" : "No"}**`));
    lines.push(line(`- Covered: ${formatNumber(v.covered_quantity)} of ${formatNumber(v.required_quantity)} required`));
    lines.push(line(`  - On hand: ${formatNumber(v.available_quantity)}`));
    lines.push(line(`  - Inbound by deadline: ${formatNumber(v.on_time_inbound_quantity)}`));
    if (v.late_shipment_ids.length > 0) {
      lines.push(line(`- Late shipments: ${v.late_shipment_ids.join(", ")}`));
    }
    lines.push(line());
  }

  // --- Reasoning trace -----------------------------------------------------
  lines.push(section("Reasoning trace"));
  lines.push(line(tableHeader("#", "Phase", "Tool", "Summary")));
  for (const step of run.trace) {
    const note = step.note ? step.note.slice(0, 80) : "";
    lines.push(line(row(
      String(step.index),
      step.phase,
      step.tool ?? "—",
      note,
    )));
  }
  lines.push(line());

  // --- Agent summary -------------------------------------------------------
  lines.push(section("Agent's own summary"));
  lines.push(line(`> ${run.explanation.replace(/\n/g, "\n> ")}`));
  lines.push(line());

  // --- Grounding -----------------------------------------------------------
  if (run.grounding) {
    lines.push(section("Grounding report"));
    const g = run.grounding;
    lines.push(line(`- Attempts: ${g.attempts}`));
    lines.push(line(`- Fallback used: ${g.fallback_used ? `Yes — ${g.fallback_reason ?? "unknown reason"}` : "No"}`));
    lines.push(line(`- Regenerated: ${g.regenerated ? "Yes" : "No"}`));
    if (g.rejected_numbers.length > 0) {
      lines.push(line(`- Rejected numbers: ${g.rejected_numbers.flat().join(", ")}`));
    }
    lines.push(line());
  }

  // --- Audit log IDs -------------------------------------------------------
  lines.push(section("Audit log references"));
  lines.push(line(`Audit entry IDs written by this run: ${run.audit_log_ids.join(", ") || "none"}`));
  lines.push(line());
  lines.push(line("---"));
  lines.push(line("*Generated by the Supply Chain Agent Console. Numbers are read verbatim from tool results — none are estimated or recalculated.*"));

  return lines.join("");
}

export function downloadAuditReport(run: AgentRun): void {
  const md = buildAuditMarkdown(run);
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `audit-report-${run.run_id.slice(0, 8)}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
