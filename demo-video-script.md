# Demo Video Script

**Agri Smart Supply-Chain Recovery Agent** — runtime ≈ **4 minutes** (target 3–5).

The demo runs against the **seeded scenario**, so every number below appears on screen when you
follow along. No scripted data, no mocked responses: reset the backend, inject a real disruption
through the console, and run the agent.

**Before recording:**

```bash
# terminal 1 — backend
cd supply-chain-agent-backend
API_KEY=demo-key uvicorn app.main:app --port 8000

# terminal 2 — console
cd frontend && npm run dev        # http://localhost:5173
```

Then: paste `demo-key` into the console's **Connection** panel → click **Reset scenario**.
Record at 100%+ browser zoom; hold each beat ~2–3 s after the narration finishes.

---

## Beat 1 — The problem *(0:00 – 0:40)* · *~40s*

**On screen:** console, freshly reset. Status panel: dealer healthy, shipment inbound.

**Say:**

> "This is a supply-chain recovery system for agricultural retail. Here's a dealer in Indore who
> has promised farmers **1,000 bags of urea within 72 hours**. They hold 300 — and the missing
> **700** are already on a truck, arriving comfortably before the deadline. Three vendors, three
> warehouses, four routes — the plan is fine.
>
> Until it isn't."

**Action:** in the **Disruption** panel, open *Shipment delay* → **60 hours** → inject.

**Say:**

> "The truck slips by 60 hours. Watch the status flip red — that arrival now lands
> **twelve hours past the deadline**. The 700 bags that covered the shortfall no longer count.
> Nothing covers it. This is exactly the moment a human planner starts making phone calls."

---

## Beat 2 — Detect & decide *(0:40 – 1:30)* · *~50s*

**On screen:** click **Run recovery**. The agent feed fills in: observe → detect → investigate → optimize.

**Say:**

> "Instead, we run the agent. First it *observes* — reads live demand, shipments and routes.
> It *detects* the violated constraint from the data, not from a prompt. Then it *investigates*
> what actually exists right now, and hands the real shortage — 700 — and the real deadline to a
> **deterministic optimizer**.
>
> The optimizer ranks every way to close the gap on three axes: **cost, delivery time and carbon** —
> 40 / 40 / 20. Six candidates exist; four are excluded, because no single warehouse or vendor
> holds 700 bags. Two survive. The winner: **purchase 700 bags from Bharat Urea Traders —
> ₹255,500, arriving in 12 hours, 2,940 kg of carbon, score 0.00**.
>
> The agent didn't do that arithmetic in its head. The optimizer did — and the agent can't
> override it."

---

## Beat 3 — Execute *(1:30 – 2:10)* · *~40s*

**On screen:** the `EXECUTE` row in the feed. Expand **view tool call** to show the raw JSON.

**Say:**

> "The chosen action is validated as structured JSON and authorised against that ranking — tool,
> target and quantity must all match, or nothing runs. Then the purchase executes: a new shipment
> is created, the vendor's stock drops from 1,200 to 500, and an audit entry records the whole
> thing as actor **agent** — before/after values, timestamped.
>
> The agent cannot act without leaving a signed trace, and it cannot invent an action: ten tools
> are its entire reach, and the three that change state go through the same validator a human
> operator uses."

---

## Beat 4 — Verify & be honest about it *(2:10 – 2:50)* · *~40s*

**On screen:** the `VERIFY` row, then the outcome card.

**Say:**

> "The agent re-reads the state and verifies itself: 300 on hand plus 700 arriving before the
> deadline is **1,000 against a requirement of 1,000** — satisfied, in under a second, with the
> late shipment still correctly flagged.
>
> One honest detail: `/demand` still shows the shortfall, because it counts stock *on hand*, while
> verification counts *coverage*. The system reports both verdicts rather than hiding the
> disagreement — that gap between the two is a known limitation, and it's the first thing on our
> list to fix.
>
> Also worth noting: every number in the agent's summary is checked against its recorded tool
> results before it's shown. If the language model cites a figure that came from nowhere, the
> whole answer is thrown out and regenerated."

---

## Beat 5 — Adaptation *(2:50 – 3:30)* · *~40s*

**On screen:** inject a second disruption, run recovery again, show the new ranking.

**Say:**

> "Now we invalidate the world it planned against — block the primary route into the dealer and
> spike demand further, and run the agent again.
>
> It re-ranks from scratch: the previous vendor no longer holds 700 bags after our purchase, so
> the top option is now the other supplier — **more expensive, but still inside the deadline** —
> and the agent executes that instead, with a fresh audit trail. The plan changed because the
> *data* changed. That's the whole point: recovery decisions follow the live state, and every
> step of the reasoning is on the record."

---

## Beat 6 — Wrap-up *(3:30 – 4:00)* · *~30s*

**On screen:** scroll the audit trail (every entry attributed), then the outcome card, then the
repository README.

**Say:**

> "Final state: the dealer's requirement is covered, every shipment the agent arranged lands
> before the deadline, and the audit trail shows every mutation — human and agent — attributed
> and timestamped.
>
> Under the hood: a FastAPI backend with a deterministic recovery optimizer, a React console,
> **264 offline tests**, API-key auth on every state change, rate limiting, and an LLM that is
> fully optional — the system runs, decides and explains itself with no external API at all.
>
> It doesn't just recover the supply chain. It shows its work."

**End card (3 s):** project name · GitHub URL · "Reset · Disrupt · Recover".

---

## Recording checklist

- [ ] Backend up with `API_KEY=demo-key`; console connected (green **Live** light)
- [ ] **Reset scenario** pressed so the status panel shows the healthy seed state
- [ ] Disruption presets ready: *shipment delay 60 h*, *route block*, *demand spike*
- [ ] Agent feed reveal set to slow enough to narrate (or use **Skip** and zoom on rows)
- [ ] `demo.py` optionally shown at the end: `python demo.py` → "39 checks, 0 failed"

## Fallback (if live demo misbehaves)

The same beats work from `python demo.py` (scripted single run, 39 assertions) — narrate over its
terminal output, showing the same numbers. `evaluate.py --runs 8 --seed 2026` gives the batch
results for the wrap-up.

---

*Numbers in this script come from the seeded scenario and the logged demo run — see
[EVALUATION.md](supply-chain-agent-backend/EVALUATION.md) and
[PRESENTATION.md](supply-chain-agent-backend/PRESENTATION.md) for the full measured context.*
