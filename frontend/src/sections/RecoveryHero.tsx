import { Arrow, RidgeMark } from "../art/Icons";
import { tornShape, type Point } from "../art/torn";

/** Collage layers, back to front, in a 1440 × 940 frame. */
const W = 1440;
const H = 940;

const layer = (points: Point[], torn: boolean[], seed: number, amplitude = 7) =>
  tornShape(points, torn, seed, amplitude);

const GREEN_BAND = layer(
  [[260, 900], [1440, 236], [1440, 760], [760, H]],
  [true, false, false, false],
  4,
  9,
);
const CREAM_STRIP = layer(
  [[400, 836], [1268, 372], [1310, 452], [520, 896]],
  [true, false, true, false],
  12,
);
const PHOTO_WINDOW = layer(
  [[640, 900], [1440, 500], [1440, H], [640, H]],
  [true, false, false, false],
  21,
  8,
);
const TERRACOTTA_SCRAP = layer(
  [[500, 834], [900, 664], [944, 742], [600, 910]],
  [true, true, true, true],
  33,
  6,
);
const OLIVE_FLOOR = layer(
  [[0, 790], [420, 742], [820, H], [0, H]],
  [true, true, false, false],
  41,
  8,
);
const PAPER_FLOOR = layer(
  [[-20, 904], [720, 872], [1460, 910], [1460, H + 4], [-20, H + 4]],
  [true, true, false, false, false],
  57,
  6,
);

export type DemoStep = 1 | 2 | 3;

const STEP_NOTE: Record<DemoStep, string> = {
  1: "Reset · start from the seeded scenario",
  2: "Inject · something in the network has broken",
  3: "Recover · the agent has acted and verified",
};

/**
 * The stress-test spread. Torn paper strata rise from the bottom of the page
 * under a painted sun; a photograph of the road shows through the tear. The
 * counter is the demo's real progress, not a carousel index.
 */
export function RecoveryHero({
  step,
  canRun,
  running,
  blockedReason,
  onRun,
}: {
  step: DemoStep;
  canRun: boolean;
  running: boolean;
  blockedReason: string | null;
  onRun: () => void;
}) {
  return (
    <section className="collage" id="stress-test" aria-labelledby="collage-title">
      <div className="collage__bar">
        <a className="collage__logo" href="#stress-test">
          <RidgeMark className="collage__logo-mark" />
          <span className="collage__logo-word">Agri Smart</span>
          <span className="collage__logo-tag">
            Recovery that
            <br />
            stays on time
          </span>
        </a>
        <ul className="collage__links">
          <li><a href="#disruptions">Disruptions</a></li>
          <li><a href="#agent">Agent</a></li>
          <li><a href="#verification">Verification</a></li>
          <li><a href="#decision">Decision</a></li>
        </ul>
        <button
          type="button"
          className="ink-pill"
          disabled={!canRun || running}
          title={blockedReason ?? "Observe, decide, act, verify — one pass"}
          onClick={onRun}
        >
          {running ? "Agent working…" : "Run recovery"} <Arrow />
        </button>
      </div>

      <div className="collage__stage">
        <svg className="collage__art" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMax slice" aria-hidden="true">
          <defs>
            <clipPath id="photo-window">
              <path d={PHOTO_WINDOW} />
            </clipPath>
          </defs>
          <circle cx="930" cy="250" r="196" fill="var(--terracotta)" filter="url(#pigment)" />
          <path d={GREEN_BAND} fill="var(--olive)" filter="url(#lift)" />
          <path d={GREEN_BAND} fill="var(--olive)" filter="url(#paper-grain)" />
          <path d={CREAM_STRIP} fill="var(--paper-hi)" stroke="#fffdf6" strokeWidth="5" filter="url(#lift)" />
          <path d={CREAM_STRIP} fill="var(--paper-deep)" filter="url(#paper-grain)" opacity="0.6" />
          <path d={PHOTO_WINDOW} fill="#fffdf6" stroke="#fffdf6" strokeWidth="12" filter="url(#lift)" />
          <image
            href="/images/truck-road.jpg"
            x="600"
            y="420"
            width="860"
            height="540"
            preserveAspectRatio="xMidYMid slice"
            clipPath="url(#photo-window)"
          />
          <path d={TERRACOTTA_SCRAP} fill="var(--terracotta)" stroke="#f6dcc8" strokeWidth="4" filter="url(#lift)" />
          <path d={TERRACOTTA_SCRAP} fill="var(--terracotta)" filter="url(#pigment)" />
          <path d={OLIVE_FLOOR} fill="var(--olive)" stroke="#e9e4d2" strokeWidth="4" filter="url(#lift)" />
          <path d={OLIVE_FLOOR} fill="var(--olive)" filter="url(#paper-grain)" />
          <path d={PAPER_FLOOR} fill="var(--paper)" stroke="#fffdf6" strokeWidth="5" filter="url(#lift)" />
        </svg>

        <p className="collage__aside">
          Farms
          <br />
          Routes
          <br />
          Dealers
          <br />
          A steadier harvest
        </p>
        <p className="collage__script">
          More than
          <br />
          a shipment
        </p>

        <div className="collage__copy">
          <p className="collage__eyebrow">
            Recover in a more
            <br />
            measured way
          </p>
          <h2 id="collage-title">A Smarter Way to Recover</h2>
          <p className="collage__sub">
            Real disruptions. Measured responses.
            <br />
            A recovery you can verify.
          </p>
          <a className="ink-pill" href="#disruptions">
            Inject a disruption <Arrow />
          </a>
          <p className="collage__counter" aria-label={`Demo step ${step} of 3: ${STEP_NOTE[step]}`}>
            <span className="collage__counter-now">0{step}</span>
            <span aria-hidden="true"> / 03</span>
            <span className="collage__counter-note">{STEP_NOTE[step]}</span>
          </p>
        </div>
      </div>
    </section>
  );
}
