import { createClient } from "@/lib/supabase/server";
import { serverFetchJson } from "@/lib/serverApi";
import type { InboundLead, InboundResult } from "@/lib/api";
import { InboundLeadsClient } from "./InboundLeadsClient";

function last30DaysIst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() - 29 * 86400000));
}

const RESULTS: InboundResult[] = ["none", "booked", "paid", "lost"];

export default async function InboundLeadsPage({ searchParams }: { searchParams?: { result?: string } }) {
  // ?result=none (Reports › Overview "chats not marked yet") opens with that filter on.
  const initialResult = RESULTS.find((r) => r === searchParams?.result);
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const inboundLeads = await serverFetchJson<{ data: InboundLead[]; total: number; page: number; limit: number }>(
    // The page opens on the last 30 days, 50 a page (InboundLeadsClient's first view).
    `/api/v1/inbound-leads/?limit=50&date_from=${last30DaysIst()}`,
    token,
  );

  return <InboundLeadsClient fallbackInboundLeads={initialResult ? null : inboundLeads} initialResult={initialResult} />;
}
