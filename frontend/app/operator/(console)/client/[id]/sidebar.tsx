"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  LayoutDashboard, MessageSquare, Users, RadioTower, Upload,
  FileCheck, Layers, BookOpen, BarChart2, Phone, Calendar, StickyNote,
  Wrench, Activity, Settings, Settings2, Database, ChevronDown, ChevronRight,
  ArrowLeft, FileText, Trash2, Cpu, ShieldCheck, Brain, Lock,
} from "lucide-react";
import { OperatorToggle } from "../../components/operator-toggle";

export type SectionType =
  | "overview" | "conversations" | "segments"
  | "inbound" | "outbound" | "templates" | "numbers"
  | "knowledge" | "analytics" | "team" | "roles"
  | "tc-upload" | "tc-dialer" | "tc-scheduled" | "tc-notes"
  | "brain" | "config" | "entitlements" | "private-send" | "token-usage" | "health" | "management" | "data-ops" | "audit-logs" | "delete-client";

type NavItem = {
  key: SectionType;
  icon: typeof LayoutDashboard;
  label: string;
  toggleKey?: string;
  dependsOn?: "outbound" | "messaging" | "any";
};

const PRODUCT_NAV: NavItem[] = [
  { key: "overview", icon: LayoutDashboard, label: "Dashboard" },
  { key: "conversations", icon: MessageSquare, label: "Conversations", dependsOn: "messaging" },
  { key: "segments", icon: Users, label: "Segments", dependsOn: "messaging" },
  { key: "inbound", icon: RadioTower, label: "Inbound Leads", toggleKey: "inbound_leads" },
  { key: "outbound", icon: Upload, label: "Outbound Leads", toggleKey: "outbound_leads" },
  { key: "templates", icon: FileCheck, label: "Templates", dependsOn: "outbound" },
  { key: "numbers", icon: Layers, label: "Numbers Pool", dependsOn: "messaging" },
  { key: "knowledge", icon: BookOpen, label: "Knowledge Base", dependsOn: "messaging" },
  { key: "analytics", icon: BarChart2, label: "Analytics", dependsOn: "messaging" },
  // Managing staff is meaningless with nothing active to staff -- Team/Roles
  // auto-follow whether ANY product feature (messaging or telecalling) is on,
  // same as everything else here, rather than getting their own independent
  // toggle that wouldn't map to any purchasable feature_catalog row.
  { key: "team", icon: Users, label: "Team", dependsOn: "any" },
  { key: "roles", icon: ShieldCheck, label: "Roles", dependsOn: "any" },
];

const TC_SUB_NAV: { key: SectionType; icon: typeof Phone; label: string; featureKey: string }[] = [
  { key: "tc-upload", icon: Upload, label: "Upload", featureKey: "telecalling.upload" },
  { key: "tc-dialer", icon: Phone, label: "Dialer", featureKey: "telecalling.dialer" },
  { key: "tc-scheduled", icon: Calendar, label: "Scheduled Calls", featureKey: "telecalling.scheduled" },
  { key: "tc-notes", icon: StickyNote, label: "Call Notes", featureKey: "telecalling.notes" },
];

const OPERATOR_NAV: NavItem[] = [
  { key: "brain", icon: Brain, label: "Anril Brain" },
  { key: "config", icon: Wrench, label: "Configuration" },
  { key: "entitlements", icon: Settings2, label: "Entitlements & Usage" },
  { key: "private-send", icon: Lock, label: "Private Send" },
  { key: "token-usage", icon: Cpu, label: "Token Consumption" },
  { key: "health", icon: Activity, label: "Health" },
  { key: "management", icon: Settings, label: "Management" },
  { key: "data-ops", icon: Database, label: "Data Ops" },
  { key: "audit-logs", icon: FileText, label: "Audit Logs" },
  { key: "delete-client", icon: Trash2, label: "Delete Client" },
];

interface SidebarProps {
  activeSection: SectionType;
  onSectionChange: (s: SectionType) => void;
  enabledFeatures: string[];
  onToggleFeature: (feature: string) => void;
  featureUpdating: boolean;
  tenantName: string;
}

export function ClientDetailSidebar({
  activeSection, onSectionChange, enabledFeatures, onToggleFeature, featureUpdating, tenantName
}: SidebarProps) {
  const [tcExpanded, setTcExpanded] = useState(true);
  const router = useRouter();

  const isEnabled = (key: string) => enabledFeatures.includes(key);
  const outboundOn = isEnabled("outbound_leads");
  const inboundOn = isEnabled("inbound_leads");
  const messagingOn = outboundOn || inboundOn;
  const telecallingOn = isEnabled("telecalling");

  function isItemEnabled(item: NavItem): boolean {
    if (item.toggleKey) return isEnabled(item.toggleKey);
    if (item.dependsOn === "outbound") return outboundOn;
    if (item.dependsOn === "messaging") return messagingOn;
    if (item.dependsOn === "any") return messagingOn || telecallingOn;
    return true;
  }

  function FeatureToggle({ featureKey, disabled }: { featureKey: string; disabled?: boolean }) {
    const on = isEnabled(featureKey);
    return (
      <span onClick={(e) => e.stopPropagation()} className="flex-shrink-0">
        <OperatorToggle
          checked={on}
          onChange={() => onToggleFeature(featureKey)}
          disabled={disabled}
          loading={featureUpdating}
          size="sm"
          aria-label={`${on ? "Disable" : "Enable"} ${featureKey.replace(/[._]/g, " ")}`}
        />
      </span>
    );
  }

  function NavItemRow({ item }: { item: NavItem }) {
    const active = activeSection === item.key;
    const enabled = isItemEnabled(item);

    return (
      <div
        onClick={() => onSectionChange(item.key)}
        className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-all duration-150 group ${
          active ? "bg-[var(--primary-50)] text-[var(--primary-800)]" : !enabled ? "opacity-40" : "text-[#0A1528] hover:bg-[#f1f5f9]"
        }`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <item.icon size={16} className={`flex-shrink-0 ${active ? "text-[var(--primary-800)]" : ""}`} />
          <span className={`text-sm font-semibold truncate ${!enabled && !active ? "line-through" : ""}`}>{item.label}</span>
        </div>
        {item.toggleKey && <FeatureToggle featureKey={item.toggleKey} />}
      </div>
    );
  }

  // Only the master "Telecalling" switch and the independent "Upload" switch
  // are interactive — Dialer/Scheduled/Notes are bundled with the master
  // switch server-side (cascade in PATCH /clients/{id}/features), so they're
  // shown as plain status rows rather than their own controls.
  function TcSubRow({ item, indent, interactive }: { item: typeof TC_SUB_NAV[0]; indent?: boolean; interactive: boolean }) {
    const active = activeSection === item.key;
    const enabled = isEnabled(item.featureKey);

    return (
      <div
        onClick={() => onSectionChange(item.key)}
        className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-all duration-150 group ${
          indent ? "ml-4" : ""
        } ${active ? "bg-[var(--primary-50)] text-[var(--primary-800)]" : !enabled ? "opacity-40" : "text-[#0A1528] hover:bg-[#f1f5f9]"}`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <item.icon size={16} className={`flex-shrink-0 ${active ? "text-[var(--primary-800)]" : ""}`} />
          <span className={`text-sm font-semibold truncate ${!enabled && !active ? "line-through" : ""}`}>{item.label}</span>
        </div>
        {interactive && <FeatureToggle featureKey={item.featureKey} />}
      </div>
    );
  }

  return (
    <aside
      className="fixed left-0 h-[calc(100vh-4rem)] w-[240px] bg-background border-r border-[#e2e8f0] flex flex-col z-30 select-none"
      style={{ top: "64px", height: "calc(100vh - 64px)" }}
    >
      <div className="px-4 py-4 border-b border-[#e2e8f0]">
        <button
          onClick={() => router.push("/operator")}
          className="flex items-center gap-1.5 text-xs text-ink-secondary hover:text-ink transition-colors mb-2"
        >
          <ArrowLeft size={12} /> Back to Clients
        </button>
        <p className="text-sm font-bold text-ink truncate">{tenantName}</p>
      </div>

      <div className="flex-grow overflow-y-auto px-3 py-3 space-y-0.5 scrollbar-thin">
        {PRODUCT_NAV.map(item => (
          <NavItemRow key={item.key} item={item} />
        ))}

        {/* Telecalling group */}
        <div>
          <div
            onClick={() => setTcExpanded(!tcExpanded)}
            className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-all duration-150 ${
              ["tc-upload", "tc-dialer", "tc-scheduled", "tc-notes"].includes(activeSection)
                ? "bg-[var(--primary-50)] text-[var(--primary-800)]" : isEnabled("telecalling") ? "text-[#0A1528] hover:bg-[#f1f5f9]" : "text-[#0A1528] opacity-40"
            }`}
          >
            <div className="flex items-center gap-3 min-w-0">
              <Phone size={16} className="flex-shrink-0" />
              <span className="text-sm font-semibold truncate">Telecalling</span>
            </div>
            <div className="flex items-center gap-2">
              <FeatureToggle featureKey="telecalling" />
              {tcExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </div>
          </div>
          {tcExpanded && (
            <div className="mt-0.5 space-y-0.5">
              {TC_SUB_NAV.map(item => (
                <TcSubRow key={item.key} item={item} indent interactive={item.key === "tc-upload"} />
              ))}
            </div>
          )}
        </div>

        <div className="pt-3 mt-3 border-t border-[#e2e8f0]">
          <p className="px-3 py-1 text-[10px] font-semibold text-ink-muted uppercase tracking-widest">Operator</p>
          {OPERATOR_NAV.map(item => (
            <NavItemRow key={item.key} item={item} />
          ))}
        </div>
      </div>
    </aside>
  );
}
