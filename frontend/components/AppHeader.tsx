"use client";
import { useState, useEffect } from "react";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
import { ChevronsDownUp, ChevronsUpDown, ClipboardList, Clock, LayoutGrid, List, Plus, ScrollText, Send, ShieldCheck, TrendingUp, Users } from "lucide-react";
import { NotificationBell } from "@/components/NotificationBell";
import { ProfileMenu } from "@/components/ProfileMenu";
import { MoreMenu } from "@/components/MoreMenu";
import { AnrilWordmark } from "@/components/logo";
import { api, API_URL, getAuthHeaders } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useHeaderAccordion } from "@/lib/headerAccordion";

import { cn } from "@/lib/utils";

const SETTINGS_ROUTE_LABELS: Record<string, string> = {
  account: "Profile & Business",
  "connect-channels": "Connect Channels",
  "auto-reply": "Auto-Reply",
  "follow-ups": "Follow-Ups",
  inbox: "Inbox & Handover",
  "telecalling-behavior": "Telecalling Behavior",
  notifications: "Notifications",
};

// Define a map of exact path matches and dynamic route prefixes
function getRouteMetadata(pathname: string, searchParams: URLSearchParams) {
  const tab = searchParams.get("tab") || "";

  if (pathname === "/dashboard") {
    return {
      title: "Product Overview",
      description: "Here's what's happening with your leads.",
    };
  }
  if (pathname === "/dashboard/outbound-leads") {
    let desc = "Import a CSV and broadcast a WhatsApp campaign to all eligible leads.";
    if (tab === "history") desc = "Track delivery status, read rates, and failures of sent broadcast campaigns.";
    if (tab === "tags") desc = "Create and manage tags to segment and label leads for outbound campaigns.";
    if (tab === "opted-out") desc = "Leads who opted out of broadcasts, globally or for one tag.";
    return {
      title: "Outbound Leads",
      description: desc,
    };
  }
  if (pathname === "/dashboard/telecalling/upload") {
    let desc = "Upload contacts, assign them to queues, and start call campaigns.";
    if (tab === "history") desc = "Review past CSV uploads, processing status, and import summaries.";
    if (tab === "scripts") desc = "Manage call scripts and guidelines for telecallers to follow.";
    return {
      title: "Telecalling Upload",
      description: desc,
    };
  }
  if (pathname === "/dashboard/telecalling") {
    return {
      title: "Telecalling Dashboard",
      description: "Manage calls, callers, and lead queues in real time.",
    };
  }
  if (pathname === "/dashboard/telecalling/scheduled") {
    return {
      title: "Scheduled Calls",
      description: "View and manage upcoming scheduled calls for leads.",
    };
  }
  if (pathname === "/dashboard/team") {
    let tabLabel = "Agent Performance";
    if (tab === "log") tabLabel = "Assignment Log";
    return {
      title: `Team Performance / ${tabLabel}`,
      description: "Add and manage telecallers under your account.",
    };
  }
  if (pathname === "/dashboard/analytics") {
    return {
      title: "Analytics",
      description: "Service metrics across all channels and the lead funnel.",
    };
  }
  if (pathname === "/dashboard/channels") {
    return {
      title: "Connect Channels",
      description: "Configure credentials and view synchronization health across your messaging channels.",
    };
  }
  if (pathname === "/dashboard/inbound-leads") {
    return {
      title: "Inbound Leads",
      description: "All inbound leads — organic and Meta Ad, across messaging channels.",
    };
  }
  if (pathname?.startsWith("/dashboard/meta-ads")) {
    return {
      title: "Meta Ads",
      description: "Meta messaging ad performance and lead attribution.",
    };
  }
  if (pathname === "/dashboard/knowledge") {
    // Documents (RAG) is the default landing tab (2026-09-20). It used to be
    // Description, back when a Description was the prerequisite for uploading;
    // nothing gates an upload any more, and uploading is what clients come here
    // to do. `?tab=description` opens the Description, and `?tab=ai-tune` is an
    // old link that still lands there.
    let tabLabel = "Documents (RAG)";
    if (tab === "description" || tab === "ai-tune") tabLabel = "Description";
    return {
      title: `Knowledge Base / ${tabLabel}`,
      description: "Upload documents and tune AI prompts to answer lead queries accurately.",
    };
  }
  if (pathname === "/dashboard/brain") {
    return {
      title: "Anril Brain",
      description: "What needs you, why customers reached a human, and what Anril knows.",
    };
  }
  if (pathname === "/dashboard/catalog") {
    let tabLabel = "Items";
    if (tab === "media") tabLabel = "Media";
    if (tab === "ai-rules") tabLabel = "AI Rules";
    if (tab === "insights") tabLabel = "Insights";
    return {
      title: `Catalogue / ${tabLabel}`,
      description: "Your products, prices and stock — what Anril can recommend and sell.",
    };
  }
  if (pathname === "/dashboard/services") {
    return {
      title: "Catalogue / Services",
      description: "What you sell in chat: packages, prices, and the details Anril collects before sending the payment link.",
    };
  }
  if (pathname === "/dashboard/leads") {
    if (tab === "reengagement") {
      return { title: "Segments / Re-engagement", description: "Group and manage your leads by attributes and behavior." };
    }
    return {
      title: "Segments",
      description: "Your leads, sorted by how ready they are to buy",
    };
  }
  if (pathname === "/dashboard/numbers") {
    // Mirror the header's own tab pills exactly -- the "WhatsApp Numbers /"
    // prefix already carries the module name, so this segment names the tab.
    let tabLabel = "Active Pool";
    if (tab === "activity") tabLabel = "Activity Log";
    return {
      title: `WhatsApp Numbers / ${tabLabel}`,
      description: "Manage sender numbers and outbound routing.",
    };
  }
  if (pathname?.startsWith("/dashboard/settings/")) {
    const segment = pathname.split("/")[3] ?? "general";
    const label = SETTINGS_ROUTE_LABELS[segment] ?? "Settings";
    return {
      title: `Account Settings / ${label}`,
      description: "Configure global parameters, voice calling and AI behavior.",
    };
  }
  if (pathname === "/dashboard/auto-messages") {
    return {
      title: "Auto-Messages",
      description: "Send your approved WhatsApp template when something happens: a form fill, a sign-up or a purchase.",
    };
  }
  if (pathname === "/dashboard/scheduled-templates") {
    return {
      title: "Scheduled templates",
      description: "Every template and broadcast waiting to go out, in one place.",
    };
  }
  if (pathname === "/dashboard/templates") {
    return {
      title: "WhatsApp Message Templates",
      description: "Create, sync and manage your WhatsApp message templates.",
    };
  }
  if (pathname === "/dashboard/templates/new") {
    return {
      title: "Create Message Template",
      description: "Design a new WhatsApp message template.",
    };
  }
  if (pathname === "/dashboard/templates/carousel") {
    return {
      title: "New Carousel Template",
      description: "Design a new WhatsApp carousel message template.",
    };
  }
  if (pathname === "/dashboard/onboarding") {
    return {
      title: "Welcome to Anril AI",
      description: "Complete your onboarding setup.",
    };
  }
  if (pathname === "/dashboard/profile") {
    return {
      title: "My performance",
      description: "Your calls, attendance and performance at a glance.",
    };
  }
  if (pathname === "/dashboard/deals") {
    return {
      title: "Deals",
      description: "Every sale in one place — WhatsApp, forms, calls and walk-ins, from quote to paid.",
    };
  }
  if (pathname === "/dashboard/notes") {
    return {
      title: "Call Review",
      description: "Browse and manage notes across your leads.",
    };
  }
  if (pathname === "/dashboard/roles") {
    return {
      title: "Users & Roles",
      description: "Define read and write access for every dashboard area, then assign one role to each team member.",
    };
  }

  // fallback/prefix matches
  if (pathname.startsWith("/dashboard/templates/")) {
    return {
      title: "Template Details",
      description: "View and manage message template configuration.",
    };
  }

  return {
    title: "Anril AI",
    description: "Your autonomous AI calling and messaging assistant.",
  };
}

export function AppHeader({ onOpenCalendar }: { onOpenCalendar: () => void }) {
  const [time, setTime] = useState<string>("");
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  // Section count + expand/collapse-all, published by a settings accordion.
  const accordion = useHeaderAccordion();

  const meta = getRouteMetadata(pathname || "", searchParams);
  const { role, permissions } = useAuthRole();
  // Owners and managers get Call Review on this route; telecallers keep the notes page and its switchers.
  const isCallReview = pathname === "/dashboard/notes" && (role === "owner" || permissions.includes("team.manage"));
  const { title, description } = isCallReview
    ? { title: "Call Review", description: "Every telecaller's calls, scores and notes, lead by lead." }
    : meta;

  const tab = searchParams.get("tab") || "";
  const leadSegment = searchParams.get("segment") || "A";
  const rolesTab = (searchParams.get("tab") === "users" || searchParams.get("tab") === "audit") ? searchParams.get("tab")! : "roles";
  const [callingProvider, setCallingProvider] = useState<"telecmi" | "sim_basic">("telecmi");

  // Deals: "Form answers" tab only shows when form intake is switched on
  const [dealsFormsEnabled, setDealsFormsEnabled] = useState(false);
  const canManageDeals = role === "owner" || permissions.includes("deals.manage");

  // Notes switcher states
  const [notesPageMode, setNotesPageMode] = useState<"by_lead" | "all_notes">("by_lead");
  const [notesViewMode, setNotesViewMode] = useState<"grid" | "list">("grid");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      // 12-hour with AM/PM in the viewer's own locale: "4:10 PM" reads at a
      // glance, "16:10" made people stop and convert.
      setTime(now.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", hour12: true }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (pathname !== "/dashboard/roles") return;
    let active = true;
    api.calls.assignmentMode().then((data) => {
      if (active) setCallingProvider(data.calling_provider ?? "telecmi");
    }).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    if (pathname !== "/dashboard/deals") return;
    let active = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/settings/intake-config`, { headers: await getAuthHeaders() });
        if (res.ok && active) setDealsFormsEnabled(Boolean((await res.json()).enabled));
      } catch {
        // No intake config: the Form answers tab stays hidden.
      }
    })();
    return () => {
      active = false;
    };
  }, [pathname]);

  // Listen to NotesClient page mode and view mode states
  useEffect(() => {
    const handlePageModeState = (e: Event) => {
      const customEvent = e as CustomEvent<"by_lead" | "all_notes">;
      setNotesPageMode(customEvent.detail);
    };
    const handleViewModeState = (e: Event) => {
      const customEvent = e as CustomEvent<"grid" | "list">;
      setNotesViewMode(customEvent.detail);
    };
    window.addEventListener("notes-page-mode-state", handlePageModeState);
    window.addEventListener("notes-view-mode-state", handleViewModeState);
    return () => {
      window.removeEventListener("notes-page-mode-state", handlePageModeState);
      window.removeEventListener("notes-view-mode-state", handleViewModeState);
    };
  }, []);

  const changeNotesPageMode = (mode: "by_lead" | "all_notes") => {
    setNotesPageMode(mode);
    window.dispatchEvent(new CustomEvent("change-notes-page-mode", { detail: mode }));
  };

  const changeNotesViewMode = (mode: "grid" | "list") => {
    setNotesViewMode(mode);
    window.dispatchEvent(new CustomEvent("change-notes-view-mode", { detail: mode }));
  };



  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center justify-between gap-3 border-b border-[#e2e8f0] bg-background px-4 lg:left-[var(--sidebar-width)] md:h-16 md:gap-4 md:px-6">
      {/* Left side: menu trigger + title and description */}
      <div className="flex min-w-0 items-center gap-3">
        <MoreMenu />
        {/* Wordmark lives here, on white, where its navy letters read; the navy sidebar carries the square mark. */}
        <AnrilWordmark height={20} className="hidden w-auto shrink-0 text-ink md:block" />
        <span className="hidden h-6 w-px shrink-0 bg-[#e2e8f0] md:block" aria-hidden="true" />
        <div className="flex min-w-0 flex-col justify-center select-none">
          <h1 className="font-display text-sm font-bold leading-tight text-on-surface md:text-base">
            {title}
          </h1>
          {description && (
            <p className="mt-0.5 hidden max-w-[650px] truncate font-body text-[11px] text-on-surface-muted sm:block">
              {description}
            </p>
          )}
        </div>
      </div>

      {/* Right side actions */}
      <div className="flex shrink-0 items-center gap-2 md:gap-2.5">
        {accordion && (
          <div className="mr-1 hidden items-center gap-2.5 md:flex">
            <span className="font-label text-[11px] font-bold uppercase tracking-[0.14em] text-on-surface-muted">
              {accordion.count} sections
              {accordion.openCount > 0 && (
                <span className="ml-1.5 font-mono text-[10px] font-semibold normal-case tracking-normal text-primary">
                  {accordion.openCount} open
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={accordion.toggleAll}
              className="inline-flex items-center gap-1.5 rounded-full border border-[#e2e8f0] bg-white px-3 py-1.5 font-label text-[11px] font-bold text-[#334155] transition-all hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
            >
              {accordion.allOpen ? <ChevronsDownUp size={13} /> : <ChevronsUpDown size={13} />}
              {accordion.allOpen ? "Collapse all" : "Expand all"}
            </button>
          </div>
        )}

        {pathname === "/dashboard/outbound-leads" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["upload", "history", "tags", "opted-out"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  params.set("tab", t);
                  router.replace(`/dashboard/outbound-leads?${params.toString()}`, { scroll: false });
                }}
                className={cn(
                  "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                  (tab === t || (t === "upload" && !tab))
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                {t === "upload" ? "Broadcast Message" : t === "history" ? "Broadcast History" : t === "tags" ? "Tags" : "Opted-Out"}
              </button>
            ))}
          </div>
        )}

        {pathname === "/dashboard/numbers" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["pool", "activity"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  if (t === "pool") params.delete("tab");
                  else params.set("tab", t);
                  const qs = params.toString();
                  router.replace(`/dashboard/numbers${qs ? `?${qs}` : ""}`, { scroll: false });
                }}
                className={cn(
                  "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                  (tab === t || (t === "pool" && tab !== "activity"))
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                {t === "pool" ? "Active Pool" : "Activity Log"}
              </button>
            ))}
          </div>
        )}

        {pathname === "/dashboard/knowledge" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["documents", "description"] as const).map((t) => {
              // Documents (RAG) leads and is the canonical no-param URL; the
              // Description follows it. `?tab=documents` stays valid for old links.
              const isDescription = tab === "description" || tab === "ai-tune";
              const isActive = t === "description" ? isDescription : !isDescription;
              return (
                <button
                  key={t}
                  onClick={() => {
                    const params = new URLSearchParams(searchParams.toString());
                    if (t === "documents") params.delete("tab");
                    else params.set("tab", t);
                    const qs = params.toString();
                    router.replace(`/dashboard/knowledge${qs ? `?${qs}` : ""}`, { scroll: false });
                  }}
                  className={cn(
                    "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                    isActive
                      ? "bg-white text-primary shadow-sm"
                      : "text-[#475569] hover:text-[#13284A]"
                  )}
                >
                  {t === "documents" ? "Documents (RAG)" : "Description"}
                </button>
              );
            })}
          </div>
        )}

        {pathname === "/dashboard/analytics" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["overview", "channels", "inbound", "templates"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  if (t === "overview") params.delete("tab");
                  else params.set("tab", t);
                  const query = params.toString();
                  router.replace(`/dashboard/analytics${query ? `?${query}` : ""}`, { scroll: false });
                }}
                className={cn(
                  "px-2.5 py-1.5 rounded-xl font-label text-xs font-bold transition-all xl:px-3",
                  (tab === t || (t === "overview" && !tab))
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                {t === "overview" ? "Overview" : t === "channels" ? "Channels" : t === "inbound" ? "Inbound" : "Templates"}
              </button>
            ))}
          </div>
        )}

        {pathname === "/dashboard/leads" && tab !== "reengagement" && (
          <div className="mr-2 hidden items-center gap-2 md:flex">
            <button
              type="button"
              onClick={() => {
                const params = new URLSearchParams(searchParams.toString());
                params.set("compose", "1");
                router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
              }}
              className="rounded-xl border border-[#e2e8f0] bg-white px-3.5 py-2 font-label text-xs font-bold text-[#0A1528] shadow-sm hover:bg-[#f1f5f9]"
            >
              <Plus size={14} className="mr-1.5 inline" />
              New message
            </button>
            <button
              type="button"
              onClick={() => {
                const params = new URLSearchParams(searchParams.toString());
                params.set("broadcast", "1");
                router.replace(`/dashboard/leads?${params.toString()}`, { scroll: false });
              }}
              className="rounded-xl bg-primary px-3.5 py-2 font-label text-xs font-bold text-white shadow-sm hover:bg-[var(--primary-900)]"
            >
              <Send size={14} className="mr-1.5 inline" />
              Message {({ A: "Hot", B: "Warm", C: "Cold", D: "Not interested" }[leadSegment] || "Hot")} leads
            </button>
          </div>
        )}

        {pathname === "/dashboard/deals" && (
          <div className="mr-2 hidden items-center gap-2 md:flex">
            <div className="flex gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1">
              {(["deals", "insights", ...(dealsFormsEnabled ? ["forms"] : [])] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    const params = new URLSearchParams(searchParams.toString());
                    if (t === "deals") params.delete("tab");
                    else params.set("tab", t);
                    const query = params.toString();
                    router.replace(`/dashboard/deals${query ? `?${query}` : ""}`, { scroll: false });
                  }}
                  className={cn(
                    "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                    (tab === t || (t === "deals" && tab !== "insights" && tab !== "forms"))
                      ? "bg-white text-primary shadow-sm"
                      : "text-[#475569] hover:text-[#13284A]"
                  )}
                >
                  {t === "deals" ? "Deals" : t === "insights" ? "Insights" : "Form answers"}
                </button>
              ))}
            </div>
            {canManageDeals && tab !== "insights" && tab !== "forms" && (
              <button
                type="button"
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  params.set("new", "1");
                  router.replace(`/dashboard/deals?${params.toString()}`, { scroll: false });
                }}
                className="rounded-xl bg-primary px-3.5 py-2 font-label text-xs font-bold text-white shadow-sm hover:bg-[var(--primary-900)]"
              >
                <Plus size={14} className="mr-1.5 inline" />
                New deal
              </button>
            )}
          </div>
        )}

        {pathname === "/dashboard/team" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["performance", "log"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  if (t === "performance") params.delete("tab");
                  else params.set("tab", t);
                  const query = params.toString();
                  router.replace(`/dashboard/team${query ? `?${query}` : ""}`, { scroll: false });
                }}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 font-label text-xs font-bold transition-all",
                  (tab === t || (t === "performance" && !tab))
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                {t === "performance" ? <TrendingUp size={13} /> : <ClipboardList size={13} />}
                {t === "performance" ? "Team & Performance" : "Assignment Log"}
              </button>
            ))}
          </div>
        )}

        {pathname === "/dashboard/roles" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["roles", "users", "audit"] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  if (item === "roles") params.delete("tab");
                  else params.set("tab", item);
                  const query = params.toString();
                  router.replace(`/dashboard/roles${query ? `?${query}` : ""}`, { scroll: false });
                }}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 font-label text-xs font-bold capitalize transition-all",
                  rolesTab === item ? "bg-white text-primary shadow-sm" : "text-[#475569] hover:text-[#13284A]",
                )}
              >
                {item === "roles" ? <ShieldCheck size={13} /> : item === "users" ? <Users size={13} /> : <ScrollText size={13} />}
                {item === "audit" ? "Audit Log" : item}
              </button>
            ))}
          </div>
        )}

        {pathname === "/dashboard/roles" && (
          <div className="hidden rounded-xl border border-border-subtle bg-white px-3 py-1.5 font-body text-xs font-semibold text-ink-muted shadow-sm md:block">
            Calling provider: <span className="text-ink">{callingProvider === "sim_basic" ? "SIM Basic" : "Cloud Telephony"}</span>
          </div>
        )}

        {pathname === "/dashboard/telecalling/upload" && (
          <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
            {(["upload", "history", "scripts"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  params.set("tab", t);
                  router.replace(`/dashboard/telecalling/upload?${params.toString()}`, { scroll: false });
                }}
                className={cn(
                  "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                  (tab === t || (t === "upload" && !tab))
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                {t === "upload" ? "Upload Contacts" : t === "history" ? "Upload History" : "Scripts"}
              </button>
            ))}
          </div>
        )}

        {pathname === "/dashboard/notes" && !isCallReview && (
          <>
            <div className="hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
              <button
                onClick={() => changeNotesPageMode("by_lead")}
                className={cn(
                  "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                  notesPageMode === "by_lead"
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                By Lead
              </button>
              <button
                onClick={() => changeNotesPageMode("all_notes")}
                className={cn(
                  "px-3 py-1.5 rounded-xl font-label text-xs font-bold transition-all",
                  notesPageMode === "all_notes"
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#475569] hover:text-[#13284A]"
                )}
              >
                All Notes
              </button>
            </div>
            <div className="mr-2 hidden gap-1 rounded-2xl bg-[#e2e8f0]/60 p-1 md:flex">
              <button
                onClick={() => changeNotesViewMode("grid")}
                className={cn(
                  "p-1.5 rounded-xl transition-all",
                  notesViewMode === "grid"
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#94a3b8] hover:text-[#1e293b]"
                )}
                title="Grid view"
              >
                <LayoutGrid size={14} />
              </button>
              <button
                onClick={() => changeNotesViewMode("list")}
                className={cn(
                  "p-1.5 rounded-xl transition-all",
                  notesViewMode === "list"
                    ? "bg-white text-primary shadow-sm"
                    : "text-[#94a3b8] hover:text-[#1e293b]"
                )}
                title="List view"
              >
                <List size={14} />
              </button>
            </div>
          </>
        )}



        <button
          onClick={onOpenCalendar}
          className="hidden h-[34px] items-center gap-1.5 rounded-lg border border-[#e2e8f0] bg-transparent px-3 font-mono text-[13px] font-semibold tracking-wide text-[#0A1528] transition-all hover:bg-[#f1f5f9] sm:flex"
          title="Schedule & Notes"
        >
          <Clock size={13} className="opacity-50" />
          <span>{time || "—"}</span>
          <span className="sr-only">Schedule & Notes</span>
        </button>
        <NotificationBell />
        <ProfileMenu />
      </div>
    </header>
  );
}
