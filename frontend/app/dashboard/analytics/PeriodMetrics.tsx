"use client";

import { humanizeKey, metricKind, peopleMetricFor, type NumMap, type ReportBase } from "@/lib/reportsApi";
import { Metric, MetricGrid } from "./reportsUi";
import type { FrameTools } from "./ReportFrame";

/**
 * Tiles for the flat numbers in a report's period. `labels` gives plain names (and the order);
 * any other key the server sends is still shown, named from its key. Numbers that are people open the side sheet.
 */
export function PeriodMetrics({
  report, tools, labels, hints = {},
}: {
  report: Pick<ReportBase<NumMap>, "period" | "before">;
  tools: FrameTools;
  labels?: Record<string, string>;
  hints?: Record<string, string>;
}) {
  const period = report.period ?? {};
  const keys = labels
    ? [...Object.keys(labels).filter((k) => k in period), ...Object.keys(period).filter((k) => !(k in labels))]
    : Object.keys(period);
  const shown = keys.filter((k) => typeof period[k] === "number" || period[k] === null);
  if (shown.length === 0) return null;
  return (
    <MetricGrid>
      {shown.map((k) => {
        const label = labels?.[k] ?? humanizeKey(k);
        const metric = peopleMetricFor(k);
        return (
          <Metric
            key={k}
            statKey={k}
            label={label}
            value={period[k]}
            before={report.before ? report.before[k] ?? null : undefined}
            kind={metricKind(k)}
            hint={hints[k]}
            people={metric ? { metric } : null}
            onPeople={(ref) => tools.openPeople(ref, label)}
          />
        );
      })}
    </MetricGrid>
  );
}
