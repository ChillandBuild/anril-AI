import type { Lead } from "@/lib/api";

// Mirrors _MESSAGE_LEAD_SOURCES in backend/app/routes/calls.py: marketplace enquiries are
// fresh buyer intent, so they sit with message leads above cold uploads.
const MESSAGE_LEAD_SOURCES = new Set(["whatsapp", "instagram", "facebook", "telegram", "indiamart", "justdial", "meta_form"]);
const SEGMENT_RANK: Record<string, number> = { A: 0, B: 1, C: 2, D: 3 };

export type LeadQueueSection = "messages" | "upload";

function timeValue(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function getLeadQueueSection(lead: Pick<Lead, "source" | "last_inbound_at">): LeadQueueSection {
  const source = (lead.source || "").toLowerCase();
  return lead.last_inbound_at || MESSAGE_LEAD_SOURCES.has(source) ? "messages" : "upload";
}

export function isMessageQueueLead(lead: Pick<Lead, "source" | "last_inbound_at">): boolean {
  return getLeadQueueSection(lead) === "messages";
}

export function compareLeadQueuePriority(a: Lead, b: Lead): number {
  const sectionRank = Number(getLeadQueueSection(a) === "upload") - Number(getLeadQueueSection(b) === "upload");
  if (sectionRank !== 0) return sectionRank;

  const segmentRank = (SEGMENT_RANK[a.segment] ?? 9) - (SEGMENT_RANK[b.segment] ?? 9);
  if (segmentRank !== 0) return segmentRank;

  const aActivity = timeValue(a.last_inbound_at) || timeValue(a.assigned_at) || timeValue(a.created_at);
  const bActivity = timeValue(b.last_inbound_at) || timeValue(b.assigned_at) || timeValue(b.created_at);
  return bActivity - aActivity;
}

export function sortLeadsForCallQueue(leads: Lead[]): Lead[] {
  return [...leads].sort(compareLeadQueuePriority);
}
