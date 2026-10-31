import type { ReactNode } from "react";

import { Leaf, Ridges, ShieldCheck } from "../art/Icons";

const PROMISES = [
  { icon: <ShieldCheck />, text: ["Audited", "actions"] },
  { icon: <Leaf />, text: ["Grounded", "explanations"] },
  { icon: <Ridges />, text: ["Verified", "recovery"] },
];

/** Closing strip: a promise line, three proofs, and a circular stamp. */
export function SiteFooter({ children }: { children: ReactNode }) {
  return (
    <footer className="site-footer">
      <div className="site-footer__strip">
        <p className="site-footer__line">
          A steadier way
          <br />
          to feed the country.
        </p>
        <ul className="site-footer__promises">
          {PROMISES.map((promise) => (
            <li key={promise.text[0]}>
              {promise.icon}
              <span>
                {promise.text[0]}
                <br />
                {promise.text[1]}
              </span>
            </li>
          ))}
        </ul>
        <svg className="stamp" viewBox="0 0 120 120" aria-hidden="true">
          <defs>
            <path id="stamp-ring" d="M60 60 m-44 0 a44 44 0 1 1 88 0 a44 44 0 1 1 -88 0" />
          </defs>
          <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" strokeWidth="0.8" />
          <text>
            <textPath href="#stamp-ring" startOffset="0">
              Recover lighter · a steadier harvest tomorrow ·
            </textPath>
          </text>
          <g transform="translate(48 48)">
            <Leaf width="24" height="24" />
          </g>
        </svg>
      </div>
      <div className="site-footer__notes">{children}</div>
    </footer>
  );
}
