import { LeadsClient } from "./LeadsClient";

// No server-side lead fetch: LeadsClient loads its own page of leads (with a
// skeleton), so awaiting a seed here only delayed the page switch for data
// that was never used. The status filter is read from the URL inside LeadsClient.
export default function LeadsPage() {
  return <LeadsClient />;
}
