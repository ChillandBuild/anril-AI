import { pointsAttr, sparkPoints } from "./homeCharts";

/**
 * A small 7-day line with a dot on today. Hover (or long-press) shows "Last 7 days: Tue 5, Wed 3, ...".
 * It is drawn only when the caller has a real series: no series, no line.
 */
export function Sparkline({
  values,
  labels,
  label,
  format = (v) => String(v),
}: {
  values: readonly number[];
  /** One weekday name per value, oldest first. */
  labels: readonly string[];
  /** What the line plots ("Won per day"). Shown on hover and read by screen readers. */
  label: string;
  format?: (v: number) => string;
}) {
  const pts = sparkPoints(values);
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1];
  const tip = values.map((v, i) => `${labels[i] ?? ""} ${format(v)}`.trim()).join(", ");
  return (
    <svg
      width={84}
      height={28}
      viewBox="0 0 84 28"
      role="img"
      aria-label={`${label}, last 7 days: ${tip}`}
      className="shrink-0"
    >
      <title>{`${label}, last 7 days: ${tip}`}</title>
      <polyline
        points={pointsAttr(pts)}
        fill="none"
        className="stroke-primary-800"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last.x} cy={last.y} r={3} className="fill-primary-800 stroke-white" strokeWidth={2} />
    </svg>
  );
}
