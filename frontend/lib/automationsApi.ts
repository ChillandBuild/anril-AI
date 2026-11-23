import { apiFetch } from "@/lib/api";

/** Alerts (Settings > Alerts) and Automations (list, evening summary, come-back offer). Backend: routes/automations.py. */

const BASE = "/api/v1/automations";

export type WhoChoice = "owner" | "team" | "assigned";
export const WHO_OPTIONS: { value: WhoChoice; label: string }[] = [
  { value: "owner", label: "Owner" },
  { value: "team", label: "Whole team" },
  { value: "assigned", label: "The person it belongs to" },
];

export type AlertRow = {
  key: string;
  label: string;
  area: string;
  who: WhoChoice[];
  how: string[];
  on: boolean;
  comes_through_in_quiet_time: boolean;
};

export type QuietTime = {
  on: boolean;
  start_hour: number;
  end_hour: number;
  is_default: boolean;
  still_comes_through: string[];
};

export type AlertsView = { alerts: AlertRow[]; quiet_time: QuietTime; who_labels: Record<string, string> };

export type AutomationRow = {
  key: string;
  name: string;
  kind: string;
  on: boolean;
  template_name: string | null;
  template_status: string | null;
  paused_reason: string | null;
  paused: boolean;
  href: string;
  switchable?: boolean;
  note?: string | null;
};

export type AutomationList = { automations: AutomationRow[]; paused_count: number };

export type EveningSummary = {
  on: boolean;
  template_name: string;
  template_status: string | null;
  waiting_for_approval: boolean;
  note: string | null;
  last_sent_on?: string | null;
  sends_at: string;
  template_body: string;
};

export type ApprovedTemplate = { name: string; body_text?: string; language?: string };

export type ComebackOffer = {
  on: boolean;
  template_name: string | null;
  offer: string;
  code: string;
  ends_on: string | null;
  template_status: string | null;
  cost_note: string;
  rules: string;
  waiting_for_approval: boolean;
  approved_templates: ApprovedTemplate[];
};

export type ComebackInput = {
  on: boolean;
  template_name: string | null;
  offer: string;
  code: string;
  ends_on: string | null;
};

const put = <T>(path: string, body: unknown) =>
  apiFetch<T>(`${BASE}${path}`, { method: "PUT", body: JSON.stringify(body) });

export const automationsApi = {
  alerts: () => apiFetch<AlertsView>(`${BASE}/alerts`),
  setAlert: (key: string, on: boolean, who?: WhoChoice[]) =>
    put<AlertRow>(`/alerts/${encodeURIComponent(key)}`, who ? { on, who } : { on }),
  setQuietTime: (on: boolean, start_hour: number, end_hour: number) =>
    put<QuietTime>("/quiet-time", { on, start_hour, end_hour }),
  list: () => apiFetch<AutomationList>(`${BASE}/list`),
  toggle: (key: string, on: boolean) => put<{ ok: boolean; key: string; on: boolean }>("/toggle", { key, on }),
  eveningSummary: () => apiFetch<EveningSummary>(`${BASE}/evening-summary`),
  setEveningSummary: (on: boolean) => put<EveningSummary>("/evening-summary", { on }),
  submitEveningTemplate: () => apiFetch<Record<string, unknown>>(`${BASE}/evening-summary/template`, { method: "POST" }),
  comeback: () => apiFetch<ComebackOffer>(`${BASE}/comeback-offer`),
  setComeback: (body: ComebackInput) => put<ComebackOffer>("/comeback-offer", body),
};

/** 21 -> "9 PM", 0 -> "12 AM", 12 -> "12 PM". */
export function hourLabel(h: number): string {
  const n = ((Math.trunc(h) % 24) + 24) % 24;
  const suffix = n < 12 ? "AM" : "PM";
  const twelve = n % 12 === 0 ? 12 : n % 12;
  return `${twelve} ${suffix}`;
}

export const HOURS: { value: number; label: string }[] = Array.from({ length: 24 }, (_, h) => ({ value: h, label: hourLabel(h) }));

/** Plain words for a WhatsApp template status. */
export function statusWords(status: string | null | undefined): string {
  switch ((status || "").toUpperCase()) {
    case "APPROVED":
      return "Approved";
    case "PENDING":
    case "IN_APPEAL":
      return "Waiting for WhatsApp to approve";
    case "REJECTED":
      return "Turned down by WhatsApp";
    case "PAUSED":
      return "Paused by WhatsApp";
    case "DISABLED":
      return "Switched off by WhatsApp";
    case "":
    case undefined:
      return "";
    default:
      return status as string;
  }
}

export function groupAlertsByArea(alerts: AlertRow[]): { area: string; rows: AlertRow[] }[] {
  const order: string[] = [];
  const by: Record<string, AlertRow[]> = {};
  for (const a of alerts) {
    if (!by[a.area]) {
      by[a.area] = [];
      order.push(a.area);
    }
    by[a.area].push(a);
  }
  return order.map((area) => ({ area, rows: by[area] }));
}
