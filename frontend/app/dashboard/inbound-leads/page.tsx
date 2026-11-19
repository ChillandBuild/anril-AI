import { createClient } from "@/lib/supabase/server";
import { serverFetchJson } from "@/lib/serverApi";
import type { InboundLead } from "@/lib/api";
import { InboundLeadsClient } from "./InboundLeadsClient";

function last30DaysIst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() - 29 * 86400000));
}

export default async function InboundLeadsPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const inboundLeads = await serverFetchJson<{ data: InboundLead[]; total: number; page: number; limit: number }>(
    // The page opens on the last 30 days, 50 a page (InboundLeadsClient's first view).
    `/api/v1/inbound-leads/?limit=50&date_from=${last30DaysIst()}`,
    token,
  );

  return <InboundLeadsClient fallbackInboundLeads={inboundLeads} />;
}
