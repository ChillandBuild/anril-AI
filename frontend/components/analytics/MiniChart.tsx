import { barGeometry, lineGeometry } from "./chartGeometry";

export interface MiniChartData { kind: "bar" | "line"; labels: string[]; values: number[] }

const W = 360;
const H = 160;

/** A small inline SVG bar or line chart, drawn without a chart library so it prints cleanly. */
export function MiniChart({ chart, caption }: { chart: MiniChartData; caption?: string }) {
  const n = chart.labels.length;
  // Show about 6 labels so they never overlap.
  const every = Math.max(1, Math.ceil(n / 6));
  const bars = chart.kind === "bar" ? barGeometry(chart.labels, chart.values, W, H) : [];
  const line = chart.kind === "line" ? lineGeometry(chart.labels, chart.values, W, H) : null;
  const summary = chart.labels.map((l, i) => `${l}: ${chart.values[i]}`).join(", ");
  return (
    <figure className="min-w-0">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={caption ? `${caption}. ${summary}` : summary} className="h-auto w-full max-w-md">
        <line x1="8" y1={H - 26} x2={W - 8} y2={H - 26} stroke="#c4c7c7" strokeWidth="1" />
        {bars.map((b, i) => (
          <g key={i}>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="2" fill="var(--primary-800)">
              <title>{`${b.label}: ${b.value}`}</title>
            </rect>
            {i % every === 0 && (
              <text x={b.x + b.w / 2} y={H - 10} textAnchor="middle" fontSize="12" fill="#556274">{b.label}</text>
            )}
          </g>
        ))}
        {line && (
          <>
            <path d={line.path} fill="none" stroke="var(--primary-800)" strokeWidth="2" strokeLinejoin="round" />
            {line.points.map((p, i) => (
              <g key={i}>
                <circle cx={p.x} cy={p.y} r="3" fill="var(--primary-800)"><title>{`${p.label}: ${p.value}`}</title></circle>
                {i % every === 0 && <text x={p.x} y={H - 10} textAnchor="middle" fontSize="12" fill="#556274">{p.label}</text>}
              </g>
            ))}
          </>
        )}
      </svg>
      {caption && <figcaption className="font-label text-xs text-[#556274]">{caption}</figcaption>}
    </figure>
  );
}
