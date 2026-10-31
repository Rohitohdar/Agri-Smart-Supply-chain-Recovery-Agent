import type { Snapshot } from "../api/hooks";
import { Birds, Emblem, GranarySketch, Leaf, TruckSketch } from "../art/Icons";
import type { Tone } from "../lib/describe";

export const NAV_LINKS = [
  { href: "#field-position", label: "Field position" },
  { href: "#stress-test", label: "Stress test" },
  { href: "#agent", label: "Recovery agent" },
  { href: "#verification", label: "Verification" },
  { href: "#connection", label: "Connection" },
] as const;

/**
 * The opening spread: valley photograph with a soft wave edge, the emblem and
 * navigation, then the live headline beside hand-cut photo frames.
 *
 * The headline is the only sentence on the page that must be true right now,
 * so it is written from the snapshot rather than as a slogan.
 */
export function FieldHero({
  snapshot,
  reachable,
  tone,
  label,
  sub,
  liveText,
}: {
  snapshot: Snapshot | null;
  reachable: boolean;
  tone: Tone;
  label: string;
  sub: string;
  liveText: string;
}) {
  const dealer = snapshot?.demand.dealer_name ?? "every dealer";
  const headline = !reachable
    ? "Waiting for the field to report in."
    : tone === "danger"
      ? `${dealer} is short. Time to recover.`
      : tone === "warn"
        ? `Holding ${dealer}’s supply through a disruption.`
        : `Keeping ${dealer} supplied, on time.`;

  return (
    <header className="field-hero">
      <div className="field-hero__photo">
        <img src="/images/hero-valley.jpg" alt="" />
        <div className="field-hero__overlay">
          <p className="field-hero__title">
            Recovered in time,
            <br />
            growing forward
          </p>
          <p className="field-hero__kicker">The recovery desk</p>
        </div>
        <svg className="field-hero__wave" viewBox="0 0 1440 90" preserveAspectRatio="none" aria-hidden="true">
          <path d="M0 52 C120 20 220 18 330 40 S540 78 660 46 S880 6 1010 34 S1250 76 1440 30 V90 H0 Z" />
        </svg>
      </div>

      <div className="field-hero__brand">
        <Emblem className="field-hero__emblem" />
        <h1>
          Agri Smart <span>Recovery</span>
        </h1>
      </div>

      <nav className="pill-nav" aria-label="Sections">
        <ul>
          {NAV_LINKS.map((link) => (
            <li key={link.href}>
              <a href={link.href}>{link.label}</a>
            </li>
          ))}
        </ul>
        <a className="pill-nav__badge" href="#agent" aria-label="Go to the recovery agent">
          <Leaf />
        </a>
      </nav>

      <section className="field-story" aria-labelledby="headline">
        <div className="field-story__text">
          <h2 id="headline" className={`field-story__headline field-story__headline--${tone}`}>
            {headline}
          </h2>
          <span className="ochre-rule" aria-hidden="true" />
          <p className="field-story__sub" role="status" aria-live="polite">
            {sub}
          </p>
          <p className={`field-story__state field-story__state--${tone}`}>
            <span className="field-story__dot" aria-hidden="true" />
            {label}
            <span className="field-story__live">· {liveText}</span>
          </p>
        </div>
        <div className="field-story__figure">
          <div className="framed framed--arch">
            <img src="/images/harvest.jpg" alt="A farmer gathering wheat ahead of a combine harvester" />
          </div>
          <Birds className="field-story__birds" />
        </div>
      </section>

      <div className="field-gallery" aria-hidden="true">
        <div className="framed framed--leaf field-gallery__left">
          <img src="/images/fields-aerial.jpg" alt="" />
        </div>
        <div className="framed framed--hill field-gallery__right">
          <img src="/images/planting-crew.jpg" alt="" />
        </div>
        <GranarySketch className="field-gallery__granary" />
      </div>

      <div className="field-coda">
        <p className="field-coda__line">
          Small delays today,
          <br />
          recovered supply tomorrow.
        </p>
        <span className="ochre-rule" aria-hidden="true" />
        <TruckSketch className="field-coda__truck" />
      </div>
    </header>
  );
}
