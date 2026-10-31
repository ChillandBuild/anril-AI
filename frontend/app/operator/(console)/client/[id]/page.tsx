"use client";
import { useEffect, useState, useCallback } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { operatorFetch } from "@/lib/operator";
import { ClientDetailSidebar, type SectionType } from "./sidebar";
import { OverviewView } from "./views/overview";
import { InboxView } from "./views/inbox";
import { LeadsView } from "./views/leads";
import { ContentView } from "./views/content";
import { AnalyticsView } from "./views/analytics";
import { TeamView } from "./views/team";
import { RolesView } from "./views/roles";
import { TelecallingView } from "./views/telecalling";
import { ConfigView } from "./views/config";
import { BrainView } from "./views/brain";
import { HealthView } from "./views/health";
import { ManagementView } from "./views/management";
import { DataOpsView } from "./views/data-ops";
import { AuditLogsView } from "./views/audit-logs";
import { DeleteClientView } from "./views/delete-client";
import { EntitlementsView } from "./views/entitlements";
import { PrivateSendView } from "./views/private-send";
import { TokenUsageCard } from "./views/TokenUsageCard";

import type { OverviewData } from "./types";

const VALID_SECTIONS: SectionType[] = [
  "overview", "conversations", "segments", "inbound", "outbound",
  "templates", "numbers", "knowledge", "analytics", "team", "roles",
  "tc-upload", "tc-dialer", "tc-scheduled", "tc-notes",
  "brain", "config", "entitlements", "private-send", "token-usage", "health", "management", "data-ops", "audit-logs", "delete-client",
];

export default function ClientDetailPage() {
  const { id: tenantId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const initialSection = searchParams.get("section");
  const [section, setSection] = useState<SectionType>(
    VALID_SECTIONS.includes(initialSection as SectionType) ? (initialSection as SectionType) : "overview"
  );
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [featureUpdating, setFeatureUpdating] = useState(false);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const data = await operatorFetch<OverviewData>(`/api/v1/operator/clients/${tenantId}/overview`);
      setOverview(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { loadOverview(); }, [loadOverview]);

  async function handleToggleFeature(feature: string) {
    if (!overview) return;
    setFeatureUpdating(true);
    const current = new Set(overview.tenant.enabled_features);
    // Upload (bulk_lead_upload) is its own SKU, independent of the telecalling
    // SIM/Tele-CMI bundle, so it's excluded from this cascade.
    const tcSubs = ["telecalling.dialer", "telecalling.scheduled", "telecalling.notes"];
    const outboundDeps = ["whatsapp"];
    const messagingDeps = ["analytics"];

    if (feature === "telecalling") {
      if (current.has("telecalling")) {
        current.delete("telecalling");
        tcSubs.forEach(s => current.delete(s));
      } else {
        current.add("telecalling");
        tcSubs.forEach(s => current.add(s));
      }
    } else if (feature === "outbound_leads") {
      if (current.has("outbound_leads")) {
        current.delete("outbound_leads");
        outboundDeps.forEach(d => current.delete(d));
      } else {
        current.add("outbound_leads");
        outboundDeps.forEach(d => current.add(d));
      }
    } else if (feature === "inbound_leads") {
      if (current.has("inbound_leads")) {
        current.delete("inbound_leads");
      } else {
        current.add("inbound_leads");
      }
    } else {
      if (current.has(feature)) {
        current.delete(feature);
      } else {
        current.add(feature);
      }
    }

    const hasOutbound = current.has("outbound_leads");
    const hasInbound = current.has("inbound_leads");
    if (!hasOutbound && !hasInbound) {
      messagingDeps.forEach(d => current.delete(d));
    }

    const updated = Array.from(current);

    try {
      await operatorFetch(`/api/v1/operator/clients/${tenantId}/features`, {
        method: "PATCH",
        body: JSON.stringify({ features: updated }),
      });
      setOverview({ ...overview, tenant: { ...overview.tenant, enabled_features: updated } });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update features");
    } finally {
      setFeatureUpdating(false);
    }
  }

  if (loading && !overview) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-ink-muted text-sm">Loading...</div>
      </div>
    );
  }

  const tenant = overview?.tenant;
  const SECTION_TITLES: Record<string, { title: string; desc: string }> = {
    overview: { title: "Product Overview", desc: "Here's what's happening with your client's leads." },
    conversations: { title: "Conversations", desc: "All lead conversations across channels." },
    segments: { title: "Segments", desc: "Leads grouped by segment — Hot, Warm, Cold, Not Interested." },
    inbound: { title: "Inbound Leads", desc: "Leads from organic and advertising channels." },
    outbound: { title: "Outbound Leads", desc: "Leads imported via CSV upload." },
    templates: { title: "Templates", desc: "WhatsApp message templates and their approval status." },
    numbers: { title: "Numbers Pool", desc: "Registered phone numbers and their quality ratings." },
    knowledge: { title: "Knowledge Base", desc: "Uploaded documents powering AI responses." },
    analytics: { title: "Analytics", desc: "Messaging and telecalling performance metrics." },
    team: { title: "Team", desc: "Owner and telecaller team members." },
    "tc-upload": { title: "Telecalling / Upload", desc: "CSV upload batches for telecalling campaigns." },
    "tc-dialer": { title: "Telecalling / Dialer", desc: "Call logs and connect rates." },
    "tc-scheduled": { title: "Telecalling / Scheduled", desc: "Upcoming scheduled callbacks." },
    "tc-notes": { title: "Telecalling / Notes", desc: "Call notes from telecallers." },
    brain: { title: "Anril Brain", desc: "What Anril knows, what is waiting on the client, and how customers are handled (read-only)." },
    config: { title: "Configuration", desc: "Credential status and key settings." },
    entitlements: { title: "Entitlements & Usage", desc: "Current purchased items, subscription status, and usage this cycle (read-only)." },
    "private-send": { title: "Private Send", desc: "Client-side sending: license keys, plan cap, reply routing and usage." },
    "token-usage": { title: "Token Consumption", desc: "AI provider token usage and estimated cost, on this client's own API keys." },
    health: { title: "Health", desc: "Channel health, delivery stats, and incidents." },
    management: { title: "Management", desc: "Owner management and account actions." },
    "data-ops": { title: "Data Operations", desc: "Clear specific data types for this client." },
    "audit-logs": { title: "Audit Logs", desc: "Track admin activity for this client." },
    "delete-client": { title: "Delete Client", desc: "Permanently remove this client and all data." },
  };
  const sectionMeta = SECTION_TITLES[section] || { title: section, desc: "" };

  return (
    <>
      {/* Fixed sidebar */}
      <ClientDetailSidebar
        activeSection={section}
        onSectionChange={setSection}
        enabledFeatures={tenant?.enabled_features || []}
        onToggleFeature={handleToggleFeature}
        featureUpdating={featureUpdating}
        tenantName={tenant?.name || ""}
      />

      {/* Content area pushed right of sidebar */}
      <div className="ml-[240px]">
        {/* Section header (like AppHeader) */}
        <div
          className="sticky z-20 h-16 flex items-center justify-between gap-4 px-7 bg-background border-b border-[#e2e8f0]"
          style={{ top: "64px" }}
        >
          <div className="flex flex-col justify-center select-none">
            <h1 className="font-display text-lg font-bold text-ink leading-tight">{sectionMeta.title}</h1>
            <p className="font-body text-xs text-ink-muted mt-0.5 max-w-[650px] truncate">{sectionMeta.desc}</p>
          </div>
          {tenant && (
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                tenant.status === "active" ? "bg-green-50 text-success" : "bg-red-50 text-danger"
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${tenant.status === "active" ? "bg-success" : "bg-danger"}`} />
                {tenant.status}
              </span>
            </div>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="mx-7 mt-4 p-3 bg-red-50 border border-danger/20 rounded-xl text-sm text-danger flex items-center justify-between">
            {error}
            <button onClick={() => setError(null)} className="text-xs underline ml-2">dismiss</button>
          </div>
        )}

        {/* Main content */}
        <div className="px-7 py-6">
          <SectionContent section={section} tenantId={tenantId} overview={overview} onReload={loadOverview} setError={setError} onOpenSection={setSection} onToggleFeature={handleToggleFeature} featureUpdating={featureUpdating} />
        </div>
      </div>
    </>
  );
}

function SectionContent({ section, tenantId, overview, onReload, setError, onOpenSection, onToggleFeature, featureUpdating }: {
  section: SectionType; tenantId: string; overview: OverviewData | null;
  onReload: () => void; setError: (e: string | null) => void;
  onOpenSection: (section: SectionType) => void;
  onToggleFeature: (feature: string) => void; featureUpdating: boolean;
}) {
  switch (section) {
    case "overview":
      return overview ? <OverviewView stats={overview.stats} /> : null;
    case "conversations":
      return <InboxView tenantId={tenantId} />;
    case "segments":
      return <LeadsView tenantId={tenantId} subSection="segments" />;
    case "inbound":
      return <LeadsView tenantId={tenantId} subSection="inbound" />;
    case "outbound":
      return <LeadsView tenantId={tenantId} subSection="outbound" />;
    case "templates":
      return <ContentView tenantId={tenantId} subSection="templates" />;
    case "numbers":
      return <ContentView tenantId={tenantId} subSection="numbers" />;
    case "knowledge":
      return <ContentView tenantId={tenantId} subSection="knowledge" />;
    case "analytics":
      return <AnalyticsView tenantId={tenantId} />;
    case "team":
      return <TeamView tenantId={tenantId} />;
    case "roles":
      return <RolesView tenantId={tenantId} />;
    case "tc-upload":
      return <TelecallingView tenantId={tenantId} subSection="upload" />;
    case "tc-dialer":
      return <TelecallingView tenantId={tenantId} subSection="dialer" />;
    case "tc-scheduled":
      return <TelecallingView tenantId={tenantId} subSection="scheduled" />;
    case "tc-notes":
      return <TelecallingView tenantId={tenantId} subSection="notes" />;
    case "brain":
      return <BrainView tenantId={tenantId} onOpenSection={onOpenSection} />;
    case "config":
      return <ConfigView tenantId={tenantId} />;
    case "entitlements":
      return <EntitlementsView tenantId={tenantId} />;
    case "private-send":
      return (
        <PrivateSendView
          tenantId={tenantId}
          enabledFeatures={overview?.tenant.enabled_features || []}
          onToggleFeature={onToggleFeature}
          featureUpdating={featureUpdating}
        />
      );
    case "token-usage":
      return <TokenUsageCard tenantId={tenantId} />;
    case "health":
      return <HealthView tenantId={tenantId} />;
    case "management":
      return <ManagementView tenantId={tenantId} overview={overview} onReload={onReload} setError={setError} />;
    case "data-ops":
      return <DataOpsView tenantId={tenantId} clientName={overview?.tenant.name || ""} />;
    case "audit-logs":
      return <AuditLogsView tenantId={tenantId} clientName={overview?.tenant.name || ""} />;
    case "delete-client":
      return <DeleteClientView tenantId={tenantId} clientName={overview?.tenant.name || ""} />;
    default:
      return (
        <div className="flex items-center justify-center h-48 text-ink-muted text-sm">
          {section} — coming soon
        </div>
      );
  }
}
