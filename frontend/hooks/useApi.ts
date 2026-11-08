import useSWR, { SWRConfiguration } from "swr";
import {
  api,
  AnalyticsOverview,
  Caller,
  Lead,
  TeamMember,
  CallerStats,
  CallLog,
  NoteWithLead,
  InboundLead,
  AdFilterTree,
  AdPerformanceRow,
  AdPerformanceParams,
  AllAdsParams,
  AllAdsResponse,
  MetaFieldCatalog,
  SyncStartInfo,
  TrackedAd,
  AdBreakdownKey,
  AdBreakdownResponse,
} from "@/lib/api";

import { fetchNotes } from "@/app/dashboard/telecalling/lib/notes-api";
import type { NotesResponse } from "@/app/dashboard/telecalling/types";

// Shared SWR defaults: cache + revalidate on focus/reconnect, dedupe bursts.
// No global polling — pages opt in via refreshInterval where freshness matters.
const defaultConfig: SWRConfiguration = {
  revalidateOnFocus: true,
  revalidateOnReconnect: true,
  dedupingInterval: 5_000,
  errorRetryCount: 2,
  shouldRetryOnError: (error) => {
    const status = (error as { status?: number } | undefined)?.status;
    return !status || ![401, 403, 404].includes(status);
  },
};

export function useOverview(enabled = true, fallbackData?: AnalyticsOverview) {
  return useSWR<AnalyticsOverview>(
    enabled ? "analytics/overview" : null,
    () => api.analytics.overview(),
    { ...defaultConfig, fallbackData },
  );
}

export interface AdminDashboardData {
  callers: Caller[];
  topLeads: Lead[];
  totalCallsToday: number;
  totalConversionsToday: number;
}

export function useAdminDashboard(fallbackData?: AdminDashboardData) {
  return useSWR<AdminDashboardData>(
    "telecalling/admin-dashboard",
    async () => {
      const [callersRes, topLeads, stats] = await Promise.all([
        api.callers.list(),
        api.leads.list({ limit: 5 }),
        api.calls.statsToday().catch(() => ({ calls_today: 0, conversions_today: 0 })),
      ]);
      return {
        callers: callersRes.data,
        topLeads,
        totalCallsToday: stats.calls_today,
        totalConversionsToday: stats.conversions_today,
      };
    },
    { ...defaultConfig, refreshInterval: 30_000, fallbackData },
  );
}

export function useLeads(
  params: {
    segment?: string;
    limit?: number;
    skip?: number;
    assigned_to?: string;
    source_filter?: string;
    broadcast_id?: string;
    ad_campaign_id?: string;
    date_from?: string;
    date_to?: string;
    search?: string;
  },
  enabled = true,
  fallbackData?: Lead[],
) {
  const key = enabled ? `leads:${JSON.stringify(params)}` : null;
  return useSWR<Lead[]>(
    key,
    () => api.leads.list(params),
    { ...defaultConfig, fallbackData },
  );
}

export function useLeadsPage(params: Parameters<typeof api.leads.listPage>[0], enabled = true) {
  const key = enabled ? `leadsPage:${JSON.stringify(params)}` : null;
  return useSWR<{ data: Lead[]; total: number }>(key, () => api.leads.listPage(params), { ...defaultConfig, keepPreviousData: true });
}

export function useTeamList(
  enabled = true,
  fallbackData?: { data: TeamMember[]; calling_provider?: "telecmi" | "sim_basic" },
) {
  return useSWR<{ data: TeamMember[]; calling_provider?: "telecmi" | "sim_basic" }>(
    enabled ? "team/list" : null,
    () => api.team.list(),
    { ...defaultConfig, fallbackData },
  );
}

export function useCallers(enabled = true, fallbackData?: Caller[]) {
  return useSWR<{ data: Caller[]; admin_caller: Caller | null }>(
    enabled ? "callers/list" : null,
    () => api.callers.list(),
    { ...defaultConfig, fallbackData: fallbackData ? { data: fallbackData, admin_caller: null } : undefined },
  );
}

export function useMyStats(enabled = true, fallbackData?: CallerStats) {
  return useSWR<CallerStats>(
    enabled ? "callers/my-stats" : null,
    () => api.callers.myStats(),
    { ...defaultConfig, fallbackData },
  );
}

export function useMyPerformance(enabled = true, fallbackData?: { target: number; achieved: number }) {
  return useSWR<{ target: number; achieved: number }>(
    enabled ? "callers/my-performance" : null,
    () => api.callers.myPerformance(),
    { ...defaultConfig, fallbackData },
  );
}

export function useCallerLogs(callerId: string | null, enabled = true, fallbackData?: CallLog[]) {
  return useSWR<CallLog[]>(
    enabled && callerId ? `callers/${callerId}/logs` : null,
    () => api.callers.logs(callerId!),
    { ...defaultConfig, fallbackData },
  );
}

export function useLeadsWithActivity(enabled = true, fallbackData?: { data: Lead[] }) {
  return useSWR<{ data: Lead[] }>(
    enabled ? "notes/leads-with-activity" : null,
    async () => {
      try {
        // leadsWithActivity returns a partial Lead shape; the notes UI treats
        // these rows as Leads (id/name/phone/segment/score/created_at).
        return (await api.notes.leadsWithActivity()) as unknown as { data: Lead[] };
      } catch {
        const [a, b, c, d] = await Promise.all([
          api.leads.list({ segment: "A", limit: 50 }).catch(() => []),
          api.leads.list({ segment: "B", limit: 50 }).catch(() => []),
          api.leads.list({ segment: "C", limit: 50 }).catch(() => []),
          api.leads.list({ segment: "D", limit: 50 }).catch(() => []),
        ]);
        return { data: [...a, ...b, ...c, ...d] };
      }
    },
    { ...defaultConfig, fallbackData },
  );
}

export function useInboundLeads(
  params: {
    origin?: string;
    segment?: string;
    ad_campaign_id?: string;
    source?: string;
    date_from?: string;
    date_to?: string;
    page?: number;
    limit?: number;
  },
  enabled = true,
  fallbackData?: { data: InboundLead[]; total: number; page: number; limit: number },
) {
  const key = enabled ? `inbound-leads:${JSON.stringify(params)}` : null;
  return useSWR<{ data: InboundLead[]; total: number; page: number; limit: number }>(
    key,
    () => api.inboundLeads.list(params),
    { ...defaultConfig, fallbackData },
  );
}

export function useInboundCampaigns(
  enabled = true,
  fallbackData?: { id: string; campaign_name: string; platform: string }[],
) {
  return useSWR<{ id: string; campaign_name: string; platform: string }[]>(
    enabled ? "inbound-leads/campaigns" : null,
    () => api.inboundLeads.campaigns(),
    { ...defaultConfig, fallbackData },
  );
}

export function useAdFilters(enabled = true, fallbackData?: AdFilterTree) {
  return useSWR<AdFilterTree>(
    enabled ? "inbound-leads/ad-filters" : null,
    () => api.inboundLeads.adFilters(),
    { ...defaultConfig, fallbackData },
  );
}

export function useAdPerformance(
  params: AdPerformanceParams,
  enabled = true,
  fallbackData?: { data: AdPerformanceRow[] },
) {
  const key = enabled ? `ad-performance:${JSON.stringify(params)}` : null;
  return useSWR<{ data: AdPerformanceRow[] }>(
    key,
    () => api.inboundLeads.adPerformance(params),
    { ...defaultConfig, fallbackData },
  );
}

/** De-duplicated reach for the Messaging ads Total row: the ads on screen, one Meta call. */
export function useAdTotalReach(adCreativeIds: string[], dateFrom?: string, dateTo?: string) {
  const ids = [...adCreativeIds].sort();
  const key = ids.length ? `ad-total-reach:${dateFrom ?? ""}:${dateTo ?? ""}:${ids.join(",")}` : null;
  return useSWR<{ reach: number | null }>(
    key,
    () => api.inboundLeads.adPerformanceTotalReach({ ad_creative_ids: ids, date_from: dateFrom, date_to: dateTo }),
    defaultConfig,
  );
}

/** Meta's reach per campaign or ad set for the Campaigns / Ad sets views; no call at ad level.
 * `metaAdIds` undefined = every ad in the account. */
export function useReachByLevel(
  level: "campaign" | "adset" | "ad",
  range: { date_from: string; date_to: string } | null,
  metaAdIds?: string[],
) {
  const ids = metaAdIds ? [...metaAdIds].sort() : undefined;
  const key = level !== "ad" && range && (!ids || ids.length)
    ? `reach-by-level:${level}:${range.date_from}:${range.date_to}:${ids ? ids.join(",") : "*"}`
    : null;
  return useSWR<{ reach: Record<string, number> | null }>(
    key,
    () => api.inboundLeads.getReachByLevel({ level: level as "campaign" | "adset", ...range!, meta_ad_ids: ids }),
    defaultConfig,
  );
}

/** De-duplicated reach for the All ads Total row. `metaAdIds` undefined = every ad in the account. */
export function useAllAdsTotalReach(
  range: { date_from: string; date_to: string } | null,
  metaAdIds?: string[],
) {
  const ids = metaAdIds ? [...metaAdIds].sort() : undefined;
  const key = range && (!ids || ids.length)
    ? `all-ads-total-reach:${range.date_from}:${range.date_to}:${ids ? ids.join(",") : "*"}`
    : null;
  return useSWR<{ reach: number | null }>(
    key,
    () => api.inboundLeads.getAllAdsTotalReach({ ...range!, meta_ad_ids: ids }),
    defaultConfig,
  );
}

/** The Meta field catalogue is static for the life of a deploy, so it is fetched once per session. */
export function useMetaFieldCatalog() {
  return useSWR<MetaFieldCatalog>(
    "inbound-leads/meta-ads/field-catalog",
    () => api.inboundLeads.getMetaFieldCatalog(),
    { ...defaultConfig, dedupingInterval: 60 * 60_000, revalidateOnFocus: false, revalidateOnReconnect: false },
  );
}

export function useAllMetaAds(params: AllAdsParams | null) {
  const key = params
    ? `all-ads:${JSON.stringify({ ...params, fields: params.fields.join(","), breakdown: params.breakdown ?? "" })}`
    : null;
  return useSWR<AllAdsResponse>(
    key,
    () => api.inboundLeads.getAllMetaAds(params!),
    defaultConfig,
  );
}

export function useTrackedAds(enabled = true) {
  return useSWR<{ data: TrackedAd[] }>(
    enabled ? "inbound-leads/meta-ads/tracked-ads" : null,
    () => api.inboundLeads.getTrackedAds(),
    defaultConfig,
  );
}

export function useAdBreakdown(
  adCreativeId: string | null,
  params: { breakdown: AdBreakdownKey; date_from?: string; date_to?: string },
) {
  return useSWR<AdBreakdownResponse>(
    adCreativeId
      ? `ad-breakdown:${adCreativeId}:${params.breakdown}:${params.date_from ?? ""}:${params.date_to ?? ""}`
      : null,
    () => api.inboundLeads.getAdBreakdown(adCreativeId!, params),
    defaultConfig,
  );
}

export function useSyncStart(enabled = true) {
  return useSWR<SyncStartInfo>(
    enabled ? "inbound-leads/meta-ads/sync-start" : null,
    () => api.inboundLeads.getSyncStart(),
    defaultConfig,
  );
}

export function useNotes(leadId: string | null, enabled = true, fallbackData?: NotesResponse) {
  return useSWR<NotesResponse>(
    enabled && leadId ? `notes/${leadId}` : null,
    () => fetchNotes(leadId!),
    { ...defaultConfig, fallbackData },
  );
}

export function useAllNotes(enabled = true, fallbackData?: { data: NoteWithLead[] }) {
  return useSWR<{ data: NoteWithLead[] }>(
    enabled ? "notes/all" : null,
    () => api.notes.all(),
    { ...defaultConfig, fallbackData },
  );
}


