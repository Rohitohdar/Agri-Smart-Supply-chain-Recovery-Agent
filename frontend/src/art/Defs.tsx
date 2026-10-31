/**
 * Shared SVG definitions, mounted once.
 *
 * Filters give paper its grain and collage layers their lift; the clip paths
 * are the organic photo frames. Everything is in objectBoundingBox units or
 * filter-relative, so any element can reuse them through `url(#id)`.
 */
export function ArtDefs() {
  return (
    <svg className="art-defs" aria-hidden="true" focusable="false" width="0" height="0">
      <defs>
        {/* Fine fibre grain multiplied over a fill — uncoated paper. */}
        <filter id="paper-grain" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="3" seed="7" result="noise" />
          <feColorMatrix
            in="noise"
            type="matrix"
            values="0 0 0 0 0.35  0 0 0 0 0.3  0 0 0 0 0.24  0 0 0 0.55 0"
            result="fibre"
          />
          <feComposite in="fibre" in2="SourceAlpha" operator="in" result="fibreIn" />
          <feBlend in="SourceGraphic" in2="fibreIn" mode="multiply" />
        </filter>

        {/* Heavier, blotchy grain for the painted sun disc. */}
        <filter id="pigment" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035 0.05" numOctaves="4" seed="3" result="cloud" />
          <feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="9" result="fine" />
          <feColorMatrix
            in="cloud"
            type="matrix"
            values="0 0 0 0 0.45  0 0 0 0 0.2  0 0 0 0 0.1  0 0 0 0.45 0"
            result="blotch"
          />
          <feColorMatrix
            in="fine"
            type="matrix"
            values="0 0 0 0 0.3  0 0 0 0 0.15  0 0 0 0 0.08  0 0 0 0.5 0"
            result="speck"
          />
          <feMerge result="tex">
            <feMergeNode in="blotch" />
            <feMergeNode in="speck" />
          </feMerge>
          <feComposite in="tex" in2="SourceAlpha" operator="in" result="texIn" />
          <feBlend in="SourceGraphic" in2="texIn" mode="multiply" />
        </filter>

        {/* Torn layers sit slightly proud of the one beneath. */}
        <filter id="lift" x="-10%" y="-10%" width="120%" height="130%">
          <feDropShadow dx="0" dy="3" stdDeviation="3.5" floodColor="#3b2e1c" floodOpacity="0.22" />
        </filter>

        {/* Ragged bristle edge for the brushstroke mask. */}
        <filter id="bristle" x="-15%" y="-15%" width="130%" height="130%">
          <feTurbulence type="fractalNoise" baseFrequency="0.018 0.09" numOctaves="3" seed="11" result="warp" />
          <feDisplacementMap in="SourceGraphic" in2="warp" scale="26" xChannelSelector="R" yChannelSelector="G" />
        </filter>

        {/* Organic photo frames, after hand-cut mounts. */}
        <clipPath id="frame-arch" clipPathUnits="objectBoundingBox">
          <path d="M0.06,0.2 C0.1,0.03 0.32,0 0.6,0.02 C0.86,0.03 0.99,0.07 0.995,0.32 C1,0.58 0.99,0.84 0.91,0.95 C0.8,1.02 0.46,0.99 0.22,0.985 C0.05,0.975 0,0.86 0.008,0.62 C0.016,0.44 0.03,0.32 0.06,0.2 Z" />
        </clipPath>
        <clipPath id="frame-leaf" clipPathUnits="objectBoundingBox">
          <path d="M0.03,0.38 C0.07,0.08 0.3,0 0.58,0.03 C0.86,0.06 1,0.2 0.99,0.47 C0.98,0.76 0.84,0.98 0.5,0.99 C0.2,1 0.01,0.86 0.01,0.62 C0.01,0.52 0.02,0.45 0.03,0.38 Z" />
        </clipPath>
        <clipPath id="frame-hill" clipPathUnits="objectBoundingBox">
          <path d="M0,0.42 C0.02,0.16 0.2,0.06 0.42,0.13 C0.6,0 0.9,0 0.98,0.2 C1.02,0.46 1,0.8 0.92,0.93 C0.8,1 0.4,1 0.15,0.965 C0.02,0.93 -0.005,0.72 0,0.42 Z" />
        </clipPath>
      </defs>
    </svg>
  );
}
