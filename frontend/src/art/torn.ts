/**
 * Torn-paper geometry.
 *
 * Collage layers are polygons whose edges are either cut (straight) or torn
 * (jittered every few pixels). The jitter comes from a seeded generator, so a
 * shape tears the same way on every render instead of shimmering.
 */

export type Point = readonly [number, number];

function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * One closed outline. `torn[i]` says whether the edge from `points[i]` to the
 * next point is torn; untorn edges stay straight, the way a cut edge would.
 */
export function tornShape(
  points: readonly Point[],
  torn: readonly boolean[],
  seed: number,
  amplitude = 5,
  step = 6,
): string {
  const rand = seeded(seed);
  const out: string[] = [];
  // A slow drift on top of the fine jitter gives the tear its long wobble.
  let drift = 0;

  points.forEach((start, i) => {
    const end = points[(i + 1) % points.length] ?? start;
    out.push(`${start[0].toFixed(1)},${start[1].toFixed(1)}`);
    if (!torn[i]) return;
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const length = Math.hypot(dx, dy);
    const nx = -dy / length;
    const ny = dx / length;
    const steps = Math.max(Math.floor(length / step), 1);
    for (let s = 1; s < steps; s += 1) {
      const t = s / steps;
      drift = drift * 0.82 + (rand() - 0.5) * amplitude * 0.9;
      const jitter = (rand() - 0.5) * amplitude * 0.7 + drift;
      out.push(
        `${(start[0] + dx * t + nx * jitter).toFixed(1)},${(start[1] + dy * t + ny * jitter).toFixed(1)}`,
      );
    }
  });

  return `M${out.join(" L")} Z`;
}
