import { useLayoutEffect, useRef, useState } from "react";

import type { Snapshot } from "../api/hooks";
import { FramedMark, Leaf, Pin, SprigRule, Storehouse, TreeMark } from "../art/Icons";
import type { Tone } from "../lib/describe";
import { formatDateTime, formatNumber, formatRelative } from "../lib/format";
import { inboundByDeadline } from "../lib/supply";

/** The spine of the brushstroke; pins are placed along it at runtime. */
const RIBBON =
  "M548 64 C420 70 262 118 214 220 C170 314 112 372 146 468 C178 560 290 566 306 662 C320 744 252 790 262 858";

interface Node {
  key: string;
  name: string;
  role: string;
  tone: Tone;
}

/**
 * Field position as a poster: a paint stroke carrying the real supply route —
 * vendors at the brush, warehouses on the way, the dealer where the paint runs
 * out — with the three numbers that decide the day set beside it.
 */
export function NetworkPoster({ snapshot, tone }: { snapshot: Snapshot | null; tone: Tone }) {
  const spine = useRef<SVGPathElement | null>(null);
  const [points, setPoints] = useState<Array<{ x: number; y: number }>>([]);

  const nodes: Node[] = snapshot
    ? [
        ...snapshot.vendors.map((vendor) => ({
          key: `v${vendor.id}`,
          name: vendor.name,
          role: vendor.is_available ? "Vendor" : "Vendor · unavailable",
          tone: (vendor.is_available ? "ok" : "danger") as Tone,
        })),
        ...snapshot.inventory.warehouses.map((warehouse) => ({
          key: `w${warehouse.location_id}`,
          name: warehouse.name,
          role: `Warehouse · ${formatNumber(warehouse.total_quantity)} in stock`,
          tone: "info" as Tone,
        })),
        {
          key: "dealer",
          name: snapshot.demand.dealer_name,
          role: "Dealer",
          tone,
        },
      ]
    : [];

  const count = nodes.length;
  useLayoutEffect(() => {
    const path = spine.current;
    if (!path || count === 0) return;
    const total = path.getTotalLength();
    const span = count > 1 ? count - 1 : 1;
    setPoints(
      Array.from({ length: count }, (_, i) => {
        const at = path.getPointAtLength(total * (0.1 + (0.82 * i) / span));
        return { x: at.x, y: at.y };
      }),
    );
  }, [count]);

  const demand = snapshot?.demand ?? null;
  const inbound = demand ? inboundByDeadline(demand) : null;

  return (
    <section className="poster" id="field-position" aria-labelledby="poster-title">
      <ol className="poster__notes">
        <li>
          <span className="poster__icon">
            <Leaf />
          </span>
          <h3>Dealer needs</h3>
          <p>
            {demand ? `${formatNumber(demand.required_quantity)} units` : "—"}
            <br />
            {demand ? `by ${formatDateTime(demand.deadline)}` : "waiting for the backend"}
          </p>
        </li>
        <li>
          <span className="poster__icon">
            <Storehouse />
          </span>
          <h3>On hand</h3>
          <p>
            {demand ? `${formatNumber(demand.available_quantity)} units` : "—"}
            <br />
            {demand ? `at ${demand.dealer_name}` : ""}
          </p>
        </li>
        <li>
          <span className="poster__icon">
            <Pin />
          </span>
          <h3>Inbound in time</h3>
          <p>
            {inbound ? `${formatNumber(inbound.onTime)} units arriving` : "—"}
            <br />
            {inbound && inbound.late > 0
              ? `${formatNumber(inbound.late)} units arrive too late`
              : demand
                ? `${formatNumber(demand.active_shipments.length)} active shipment(s)`
                : ""}
          </p>
        </li>
      </ol>

      <div className="poster__ribbon">
        <svg viewBox="0 0 600 920" role="img" aria-label="Supply route from vendors to the dealer">
          <defs>
            <mask id="ribbon-mask" maskUnits="userSpaceOnUse" x="0" y="0" width="600" height="920">
              <g filter="url(#bristle)" fill="none" stroke="#fff" strokeLinecap="round">
                <path d={RIBBON} strokeWidth="150" />
                {[-58, -40, -22, 22, 40, 58].map((offset, i) => (
                  <path
                    key={offset}
                    d={RIBBON}
                    strokeWidth={6 + (i % 3) * 3}
                    transform={`translate(${offset * 0.25} ${offset})`}
                    strokeDasharray={`${260 + i * 40} 2000`}
                  />
                ))}
              </g>
            </mask>
          </defs>

          {/* Green paint under the photograph shows as a rim where they disagree. */}
          <g filter="url(#bristle)" fill="none" strokeLinecap="round">
            <path d={RIBBON} stroke="var(--olive)" strokeWidth="164" />
          </g>
          <image
            href="/images/highway-fields.jpg"
            x="40"
            y="0"
            width="560"
            height="920"
            preserveAspectRatio="xMidYMid slice"
            mask="url(#ribbon-mask)"
          />
          <g fill="var(--olive)">
            <path d="M226 850 C228 880 232 896 236 904 C240 896 240 880 238 852 Z" />
            <circle cx="236" cy="906" r="6" />
            <path d="M262 856 C262 870 264 878 266 882 C268 878 270 870 270 858 Z" />
            <circle cx="266" cy="884" r="4.5" />
            <path d="M292 848 C292 872 296 888 300 894 C304 888 304 872 302 846 Z" />
            <circle cx="300" cy="896" r="5.5" />
          </g>

          {/* The brush that laid the stroke. */}
          <g transform="translate(560 40) rotate(-38)">
            <path d="M-46 0 C-40 -14 -20 -18 0 -16 L0 16 C-20 18 -40 14 -46 0 Z" fill="var(--olive)" />
            <path d="M-40 -2 L-6 -10 M-40 3 L-6 10 M-44 0 L-4 0" stroke="var(--olive-bright)" strokeWidth="1.2" />
            <rect x="0" y="-15" width="34" height="30" rx="3" fill="#8d8d86" />
            <rect x="0" y="-15" width="34" height="8" rx="3" fill="#b9b8b0" />
            <path d="M34 -13 L150 -8 L150 8 L34 13 Z" fill="var(--ink)" />
            <path d="M34 -13 L150 -8 L150 -3 L34 -6 Z" fill="#46524a" />
          </g>

          <path ref={spine} d={RIBBON} fill="none" stroke="none" />
          <path
            d={RIBBON}
            fill="none"
            stroke="var(--paper-hi)"
            strokeWidth="2"
            strokeDasharray="2 9"
            strokeLinecap="round"
            opacity="0.9"
          />

          {points.length === nodes.length
            ? nodes.map((node, i) => {
                const at = points[i];
                if (!at) return null;
                const { x, y } = at;
                const flip = x > 300;
                return (
                  <g key={node.key} className={`route-node route-node--${node.tone}`} transform={`translate(${x} ${y})`}>
                    <circle r="9" className="route-node__halo" />
                    <circle r="5" className="route-node__dot" />
                    <g transform={`translate(${flip ? -16 : 16} 0)`}>
                      <text className="route-node__name" textAnchor={flip ? "end" : "start"} y="-2">
                        {node.name}
                      </text>
                      <text className="route-node__role" textAnchor={flip ? "end" : "start"} y="13">
                        {node.role}
                      </text>
                    </g>
                  </g>
                );
              })
            : null}
        </svg>
      </div>

      <div className="poster__title">
        <FramedMark className="poster__mark" />
        <h2 id="poster-title">
          <span>The</span> Supply Network
        </h2>
        <p className="poster__subtitle">Where every unit is counted before the deadline</p>
        <SprigRule className="poster__sprig" />
      </div>

      <footer className={`poster__dealer poster__dealer--${tone}`}>
        <TreeMark className="poster__tree" />
        <p className="poster__dealer-name">{demand?.dealer_name ?? "Dealer"}</p>
        <p className="poster__dealer-line">
          {demand
            ? `${formatNumber(demand.required_quantity)} units required · ${formatDateTime(demand.deadline)}`
            : "Waiting for the backend"}
        </p>
        <p className="poster__dealer-foot">
          <span aria-hidden="true">‹‹</span> updated {formatRelative(snapshot?.fetchedAt)}{" "}
          <span aria-hidden="true">››</span>
        </p>
      </footer>
    </section>
  );
}
