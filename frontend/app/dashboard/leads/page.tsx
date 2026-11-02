import { LeadsClient } from "./LeadsClient";

const SEGMENTS = ["A", "B", "C", "D"] as const;
type Segment = (typeof SEGMENTS)[number];

function isSegment(value: string | string[] | undefined): value is Segment {
  return typeof value === "string" && (SEGMENTS as readonly string[]).includes(value);
}

// No server-side lead fetch: LeadsClient loads its own page of leads (with a
// skeleton), so awaiting a seed here only delayed the page switch for data
// that was never used.
export default function LeadsPage({
  searchParams,
}: {
  searchParams: { segment?: string | string[] };
}) {
  const requestedSegment = searchParams?.segment;
  const initialTab: Segment = isSegment(requestedSegment) ? requestedSegment : "A";

  return <LeadsClient initialTab={initialTab} />;
}
