export interface BarGeom { x: number; y: number; w: number; h: number; label: string; value: number }
export interface LineGeom { points: { x: number; y: number; label: string; value: number }[]; path: string }

const PAD_X = 8;
const PAD_TOP = 14;
const PAD_BOTTOM = 26;

function top(values: number[]): number {
  return Math.max(1, ...values.map((v) => (Number.isFinite(v) ? v : 0)));
}

/** Bars scaled to the biggest value; a zero stays a thin stub so it can still be seen. */
export function barGeometry(labels: string[], values: number[], width: number, height: number): BarGeom[] {
  const n = Math.min(labels.length, values.length);
  if (n === 0) return [];
  const plotW = width - PAD_X * 2;
  const plotH = height - PAD_TOP - PAD_BOTTOM;
  const slot = plotW / n;
  const w = Math.max(2, slot * 0.7);
  const max = top(values.slice(0, n));
  return Array.from({ length: n }, (_, i) => {
    const v = Math.max(0, values[i]);
    const h = v === 0 ? 1 : Math.max(2, (v / max) * plotH);
    return { x: PAD_X + i * slot + (slot - w) / 2, y: PAD_TOP + plotH - h, w, h, label: labels[i], value: values[i] };
  });
}

export function lineGeometry(labels: string[], values: number[], width: number, height: number): LineGeom {
  const n = Math.min(labels.length, values.length);
  if (n === 0) return { points: [], path: "" };
  const plotW = width - PAD_X * 2;
  const plotH = height - PAD_TOP - PAD_BOTTOM;
  const max = top(values.slice(0, n));
  const points = Array.from({ length: n }, (_, i) => ({
    x: n === 1 ? width / 2 : PAD_X + (i / (n - 1)) * plotW,
    y: PAD_TOP + plotH - (Math.max(0, values[i]) / max) * plotH,
    label: labels[i],
    value: values[i],
  }));
  return { points, path: points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ") };
}
