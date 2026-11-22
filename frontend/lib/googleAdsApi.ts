import { API_URL, apiFetch, errorDetailText, getAuthHeaders } from "@/lib/api";

/** One campaign row. The money keys are missing for people without deals.view. */
export type GoogleAdsRow = {
  campaign_id: string;
  name: string;
  google_campaign_name: string | null;
  clicks: number | null;
  spend_source: "upload" | "hand" | null;
  chats: number;
  calls: number;
  hot: number;
  paid_orders: number;
  spent_paise?: number | null;
  paid_paise?: number;
  per_chat_paise?: number | null;
};

export type GoogleAdsTotals = Omit<GoogleAdsRow, "campaign_id" | "name" | "google_campaign_name" | "spend_source">;

export type GoogleAdsReport = {
  month: string;
  rows: GoogleAdsRow[];
  totals: GoogleAdsTotals;
  connect: { available: boolean; reason: string };
};

/** null = the report had no Cost / Clicks column; the saved value is kept. */
export type UnmatchedRow = { google_campaign_name: string; spend_paise: number | null; clicks: number | null };
export type MatchedRow = UnmatchedRow & { campaign_id: string; name: string };
export type UploadResult = {
  month: string;
  matched: MatchedRow[];
  unmatched: UnmatchedRow[];
  skipped_other_months: number;
};

const BASE = "/api/v1/google-ads";

export const googleAdsApi = {
  campaigns: (month: string) => apiFetch<GoogleAdsReport>(`${BASE}/campaigns?month=${encodeURIComponent(month)}`),
  setSpend: (campaignId: string, body: { month: string; spend_paise: number; clicks: number }) =>
    apiFetch<{ spend_paise: number; clicks: number }>(`${BASE}/campaigns/${encodeURIComponent(campaignId)}/spend`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  pair: (body: { google_campaign_name: string; campaign_id: string; month: string; spend_paise: number | null; clicks: number | null }) =>
    apiFetch<{ campaign_id: string }>(`${BASE}/pair`, { method: "POST", body: JSON.stringify(body) }),
  makeLink: (campaign: string) =>
    apiFetch<{ link: string; campaign_slug: string; campaign_id: string | null }>(`${BASE}/links`, {
      method: "POST",
      body: JSON.stringify({ campaign }),
    }),
  /** Multipart: apiFetch always sends JSON headers, so this builds its own request. */
  upload: async (month: string, file: File): Promise<UploadResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const headers = await getAuthHeaders();
    const res = await fetch(`${API_URL}${BASE}/upload?month=${encodeURIComponent(month)}`, {
      method: "POST",
      body: fd,
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(errorDetailText(err?.detail, "Upload failed"));
    }
    return res.json();
  },
};
