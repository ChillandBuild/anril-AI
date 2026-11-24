"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Plus,
  RefreshCw,
  Search,
  Filter,
  LayoutGrid,
  List,
  ChevronDown,
  Sparkles,
  Shuffle,
  Trash2,
  Eye,
  Layers,
  ChevronRight,
  Download,
  X,
  AlertCircle,
  HelpCircle,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { AiraLoader } from "@/components/AiraLoader";
import { LANGUAGES, STATUS_COLORS } from "./types";
import type { Template, TemplateUsage } from "./types";
import { NEEDS_FIX, NEEDS_FIX_STATUSES, NO_FILTERS, filterTemplates, languageOptions, statusNote, usedInOptions } from "./template-filters";
import { timeAgo } from "./template-card-model";
import { prefillFromTemplate, savePrefill } from "./template-prefill";
import type { TemplatePrefill } from "./template-prefill";
import ExcelPanel from "./components/excel-panel";
import TemplateNotes from "./components/template-notes";
import TemplateCard from "./components/template-card";
import TemplateRow from "./components/template-row";
import AiDraftDialog from "./components/ai-draft-dialog";
import WhatsAppPreview from "./components/whatsapp-preview";
import { useAuthRole } from "../contexts/AuthRoleContext";
import AiraId from "./components/aira-id";

// Remembers filters, view mode and list scroll for the session, so opening a template and coming back lands where you left off
const VIEW_STATE_KEY = "templates:view-state";
// When this browser last ran "Sync" with Meta, for the line under the buttons
const LAST_SYNC_KEY = "templates:last-sync";

type SavedViewState = {
  searchQuery: string;
  selectedCategory: string;
  selectedStatus: string;
  selectedLanguage: string;
  selectedUsedIn: string;
  viewMode: "GRID" | "TABLE";
  scrollTop: number;
};

function readViewState(): Partial<SavedViewState> {
  try {
    return JSON.parse(sessionStorage.getItem(VIEW_STATE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeViewState(patch: Partial<SavedViewState>) {
  try {
    sessionStorage.setItem(VIEW_STATE_KEY, JSON.stringify({ ...readViewState(), ...patch }));
  } catch {
    // storage unavailable (private mode) — the page still works, it just won't remember
  }
}

export default function TemplatesPage() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManageTemplates = role === "owner" || permissions.includes("templates.manage");
  const [templates, setTemplates] = useState<Template[]>([]);
  // Where each template is used. Loaded beside the list; if it fails the list still works, just without "Used in".
  const [usage, setUsage] = useState<TemplateUsage>({});
  const [usageReady, setUsageReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Sync / Action states
  const [syncing, setSyncing] = useState(false);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [excelOpen, setExcelOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");
  const [selectedStatus, setSelectedStatus] = useState<string>("ALL");
  const [selectedLanguage, setSelectedLanguage] = useState<string>("ALL");
  const [selectedUsedIn, setSelectedUsedIn] = useState<string>("ALL");
  const [viewMode, setViewMode] = useState<"GRID" | "TABLE">("GRID");

  // Scroll memory for the list area (the header above it stays locked)
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingScrollTop = useRef<number | null>(null);
  const [viewStateRestored, setViewStateRestored] = useState(false);

  // Selected Detail Modal
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);

  // Variations Modal
  const [variationsModalId, setVariationsModalId] = useState<string | null>(null);
  const [variationsList, setVariationsList] = useState<string[]>([]);
  const [newVariation, setNewVariation] = useState("");
  const [variationsLoading, setVariationsLoading] = useState(false);

  // Load templates from API
  async function loadTemplates() {
    setLoading(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/`, {
        headers: authHeaders,
      });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setTemplates(data.data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load templates");
    } finally {
      setLoading(false);
    }
    loadUsage();
  }

  async function fetchUsage(): Promise<TemplateUsage> {
    const res = await fetch(`${API_URL}/api/v1/templates/usage`, { headers: await getAuthHeaders() });
    if (!res.ok) throw new Error(`API error ${res.status}`);
    return (await res.json()).data || {};
  }

  async function loadUsage() {
    try {
      setUsage(await fetchUsage());
      setUsageReady(true);
    } catch {
      setUsageReady(false);
    }
  }

  useEffect(() => {
    loadTemplates();
  }, []);

  useEffect(() => {
    const saved = readViewState();
    if (saved.searchQuery) setSearchQuery(saved.searchQuery);
    if (saved.selectedCategory) setSelectedCategory(saved.selectedCategory);
    if (saved.selectedStatus) setSelectedStatus(saved.selectedStatus);
    if (saved.selectedLanguage) setSelectedLanguage(saved.selectedLanguage);
    if (saved.selectedUsedIn) setSelectedUsedIn(saved.selectedUsedIn);
    if (saved.viewMode === "GRID" || saved.viewMode === "TABLE") setViewMode(saved.viewMode);
    pendingScrollTop.current = saved.scrollTop ?? null;
    setViewStateRestored(true);
    try {
      setLastSynced(localStorage.getItem(LAST_SYNC_KEY));
    } catch {
      // storage unavailable: the line just doesn't say when
    }
  }, []);

  useEffect(() => {
    if (!viewStateRestored) return;
    writeViewState({ searchQuery, selectedCategory, selectedStatus, selectedLanguage, selectedUsedIn, viewMode });
  }, [viewStateRestored, searchQuery, selectedCategory, selectedStatus, selectedLanguage, selectedUsedIn, viewMode]);

  // Once the list has rendered, jump back to where the user was
  useEffect(() => {
    if (loading || !viewStateRestored || pendingScrollTop.current === null) return;
    scrollRef.current?.scrollTo({ top: pendingScrollTop.current });
    pendingScrollTop.current = null;
  }, [loading, viewStateRestored]);

  // "Download all" in the Excel panel: the whole account, fresh, so an approval since page-load is in it
  async function loadAllForExcel(): Promise<{ templates: Template[]; usage: TemplateUsage }> {
    const res = await fetch(`${API_URL}/api/v1/templates/`, { headers: await getAuthHeaders() });
    if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
    const data = await res.json();
    let fresh: TemplateUsage = usage;
    try {
      fresh = await fetchUsage();
    } catch {
      // "used in" stays as last loaded
    }
    return { templates: data.data || [], usage: fresh };
  }

  // Sync all templates from Meta
  async function handleSyncAll() {
    if (!canManageTemplates) {
      setError("Read-only role: syncing templates from Meta is disabled.");
      return;
    }
    setSyncing(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/sync-from-meta`, {
        method: "POST",
        headers: authHeaders,
      });
      if (!res.ok) throw new Error("Failed to sync templates from Meta");
      const result = await res.json();
      const now = new Date().toISOString();
      setLastSynced(now);
      try {
        localStorage.setItem(LAST_SYNC_KEY, now);
      } catch {
        // storage unavailable
      }
      await loadTemplates();
      alert(`Sync completed: ${result.total} templates synced (${result.added} added, ${result.updated} updated).`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync from Meta failed");
    } finally {
      setSyncing(false);
    }
  }

  // Single Template Actions
  async function handleSyncSingle(id: string, e?: React.MouseEvent) {
    e?.stopPropagation();
    if (!canManageTemplates) {
      setError("Read-only role: syncing template status is disabled.");
      return;
    }
    setSyncingId(id);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/${id}/sync`, {
        method: "POST",
        headers: authHeaders,
      });
      if (res.ok) {
        const updated = await res.json();
        setTemplates((prev) => prev.map((t) => (t.id === id ? updated : t)));
      }
    } catch {
      // ignore failures
    } finally {
      setSyncingId(null);
    }
  }

  async function handleDelete(id: string, e?: React.MouseEvent) {
    e?.stopPropagation();
    if (!canManageTemplates) {
      setError("Read-only role: deleting templates is disabled.");
      return;
    }
    if (!confirm("Delete this template here and on WhatsApp? If it was approved, Meta won't let you reuse its name for 30 days.")) return;
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/${id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (res.ok) {
        setTemplates((prev) => prev.filter((t) => t.id !== id));
        if (selectedTemplate?.id === id) {
          setSelectedTemplate(null);
        }
      } else {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Failed to delete template");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  // Variations Modal Logic
  function openVariationsModal(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    openVariations(id);
  }

  async function openVariations(id: string) {
    setVariationsModalId(id);
    setVariationsList([]);
    setNewVariation("");
    setVariationsLoading(true);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/${id}/variations`, {
        headers: authHeaders,
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setVariationsList(data.variations ?? []);
    } catch {
      setVariationsList([]);
    } finally {
      setVariationsLoading(false);
    }
  }

  async function handleVariationAdd() {
    if (!canManageTemplates) return;
    const nameTrimmed = newVariation.trim();
    if (!nameTrimmed || !variationsModalId) return;
    const next = [...variationsList, nameTrimmed];
    setVariationsList(next);
    setNewVariation("");
    try {
      const authHeaders = await getAuthHeaders();
      await fetch(`${API_URL}/api/v1/templates/${variationsModalId}/variations`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ variations: next }),
      });
    } catch {
      setVariationsList((prev) => prev.filter((v) => v !== nameTrimmed));
    }
  }

  async function handleVariationRemove(varName: string) {
    if (!canManageTemplates) return;
    if (!variationsModalId) return;
    const next = variationsList.filter((v) => v !== varName);
    setVariationsList(next);
    try {
      const authHeaders = await getAuthHeaders();
      await fetch(`${API_URL}/api/v1/templates/${variationsModalId}/variations`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ variations: next }),
      });
    } catch {
      setVariationsList((prev) => [...prev, varName]);
    }
  }

  // Filter Logic
  const filteredTemplates = filterTemplates(
    templates,
    { ...NO_FILTERS, search: searchQuery, category: selectedCategory, status: selectedStatus, language: selectedLanguage, usedIn: selectedUsedIn },
    usage,
  );
  const languageChoices = languageOptions(templates);
  const usedInChoices = usedInOptions(usage);

  const hasFilters = !!(searchQuery || selectedCategory !== "ALL" || selectedStatus !== "ALL" || selectedLanguage !== "ALL" || selectedUsedIn !== "ALL");
  const activeFilterCount = [
    searchQuery,
    selectedCategory !== "ALL" ? selectedCategory : "",
    selectedStatus !== "ALL" ? selectedStatus : "",
    selectedLanguage !== "ALL" ? selectedLanguage : "",
    selectedUsedIn !== "ALL" ? selectedUsedIn : "",
  ].filter(Boolean).length;

  // Calculate statistics
  const countApproved = templates.filter((t) => t.status === "APPROVED").length;
  const countPending = templates.filter((t) => t.status === "PENDING").length;
  const countRejected = templates.filter((t) => NEEDS_FIX_STATUSES.includes(t.status)).length;

  const summary = [
    { key: "APPROVED", count: countApproved, label: "Approved Templates", mid: "Approved", short: "Approved", hint: "ready to send", tone: "text-[#15803d]", edge: "border-l-[#15803d]" },
    { key: "PENDING", count: countPending, label: "Pending Review", mid: "Pending Review", short: "Pending", hint: "Meta is checking", tone: "text-[#b45309]", edge: "border-l-[#b45309]" },
    { key: NEEDS_FIX, count: countRejected, label: "Rejected / Paused", mid: "Rejected / Paused", short: "Rejected / Paused", hint: "see why and fix", tone: "text-[#c2410c]", edge: "border-l-[#dc2626]" },
  ];
  const ghostBtn =
    "flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3.5 font-label text-[13px] font-semibold text-ink shadow-sm transition-colors hover:bg-[#f8fafc] disabled:opacity-50";
  const clearFilters = () => {
    setSearchQuery("");
    setSelectedCategory("ALL");
    setSelectedStatus("ALL");
    setSelectedLanguage("ALL");
    setSelectedUsedIn("ALL");
  };
  const openBuilderWith = (p: TemplatePrefill) => {
    savePrefill(p);
    router.push("/dashboard/templates/new");
  };

  return (
    <div className="flex flex-col min-w-0 h-[calc(100dvh-11.5rem)] md:h-[calc(100dvh-7.5rem)] overflow-hidden">
      {/* Top Locked Section: summary, actions & filters */}
      <div className="shrink-0 space-y-3 pb-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start">
          {/* Summary cards: click one to show just those */}
          <div className="grid flex-1 grid-cols-3 gap-2 md:gap-3">
            {summary.map((s) => {
              const active = selectedStatus === s.key;
              return (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSelectedStatus(active ? "ALL" : s.key)}
                  aria-pressed={active}
                  className={`flex min-w-0 items-center gap-2 rounded-2xl border border-l-4 bg-white px-2.5 py-2 text-left shadow-sm transition-all hover:shadow-md md:gap-3 md:px-4 md:py-2.5 ${s.edge} ${
                    active ? "border-primary-300 ring-2 ring-primary-100" : "border-[#e7e2da]"
                  }`}
                >
                  <span className={`font-display text-2xl font-bold tabular-nums md:text-[28px] ${s.tone}`}>
                    {loading ? <span className="inline-block h-6 w-5 animate-pulse rounded bg-[#f1f5f9] align-middle" /> : s.count}
                  </span>
                  <span className="min-w-0 leading-tight">
                    <span className="block font-label text-[12.5px] font-bold text-ink md:truncate md:text-[15px]">
                      <span className="md:hidden">{s.short}</span>
                      <span className="hidden md:inline 2xl:hidden">{s.mid}</span>
                      <span className="hidden 2xl:inline">{s.label}</span>
                    </span>
                    <span className="hidden truncate text-[12.5px] text-ink-muted md:block">{s.hint}</span>
                  </span>
                </button>
              );
            })}
          </div>

          {/* Actions */}
          <div className="flex shrink-0 flex-col gap-1.5 xl:items-end">
            <div className="grid grid-cols-6 gap-2 md:flex md:flex-wrap md:items-center">
              <button
                onClick={handleSyncAll}
                disabled={syncing || !canManageTemplates}
                title={canManageTemplates ? "Get the latest templates and approvals from Meta" : "Read-only role: sync is disabled"}
                className={`${ghostBtn} col-span-2`}
              >
                <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
                {syncing ? "Syncing…" : "Sync"}
              </button>
              <Link href="/dashboard/templates/carousel" className={`${ghostBtn} col-span-2`}>
                <Layers size={14} />
                Carousel
              </Link>
              <button onClick={() => setExcelOpen(true)} title="Upload many templates, or download all of them, as Excel" className={`${ghostBtn} col-span-2`}>
                <Download size={14} />
                Excel
              </button>
              {canManageTemplates && (
                <button onClick={() => setAiOpen(true)} className={`${ghostBtn} order-first col-span-3 border-primary-200 text-primary hover:bg-primary-50 md:order-none`}>
                  <Sparkles size={14} />
                  Write with AI
                </button>
              )}
              <Link
                href="/dashboard/templates/new"
                className={`order-first ${canManageTemplates ? "col-span-3" : "col-span-6"} flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 md:order-none font-label text-[13px] font-semibold text-white shadow-md shadow-primary-200 transition-colors hover:bg-primary/90`}
              >
                <Plus size={15} />
                Create Template
              </Link>
            </div>
            <p className="hidden text-[12px] text-ink-muted md:block xl:text-right">
              {lastSynced ? `Synced with Meta ${timeAgo(lastSynced)}` : "Meta updates approvals here as they happen"} · Excel = upload many or download all
            </p>
          </div>
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-xl text-sm flex items-center gap-2 animate-slide-up">
            <AlertCircle size={15} />
            <span>{error}</span>
          </div>
        )}

        {/* Filter bar */}
        <div className="rounded-2xl border border-[#e7e2da] bg-white p-2 shadow-sm md:p-2.5">
          <div className="flex flex-wrap items-center gap-2 xl:flex-nowrap">
            <div className="hidden shrink-0 items-center gap-2 pr-1 md:flex">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-50 text-primary-700">
                <Filter size={14} />
              </span>
              <div className="leading-tight">
                <span className="block font-label text-[14px] font-bold text-ink">Filter Results</span>
                <span className="block text-[12px] text-ink-muted">
                  {loading ? "Loading…" : `${filteredTemplates.length} template${filteredTemplates.length === 1 ? "" : "s"}`}
                </span>
              </div>
            </div>

            <div className="relative min-w-0 flex-1 basis-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name or words in the message"
                aria-label="Search templates"
                style={{ paddingLeft: "2.1rem", paddingRight: searchQuery ? "1.9rem" : "0.75rem" }}
                className="h-10 w-full rounded-xl border border-[#e2e8f0] bg-white text-[13.5px] text-ink placeholder:text-[#94a3b8] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-100"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery("")} aria-label="Clear search" className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] hover:text-ink">
                  <X size={13} />
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={() => setFiltersOpen((v) => !v)}
              aria-expanded={filtersOpen}
              className="flex h-10 shrink-0 items-center gap-1.5 rounded-xl border border-[#e2e8f0] bg-white px-3 text-[13px] font-semibold text-ink md:hidden"
            >
              <ChevronDown size={14} className={`transition-transform ${filtersOpen ? "rotate-180" : ""}`} />
              Filter · {activeFilterCount - (searchQuery ? 1 : 0)}
            </button>

            <div className={`${filtersOpen ? "grid" : "hidden"} w-full grid-cols-2 gap-2 md:flex md:w-auto md:flex-wrap md:items-center xl:flex-nowrap`}>
              <Select
                size="sm"
                aria-label="Filter by type"
                className="md:w-[140px]"
                value={selectedCategory}
                onChange={setSelectedCategory}
                options={[
                  { value: "ALL", label: "All Types" },
                  { value: "MARKETING", label: "Marketing" },
                  { value: "UTILITY", label: "Utility" },
                  { value: "AUTHENTICATION", label: "Authentication" },
                ]}
              />
              <Select
                size="sm"
                aria-label="Filter by status"
                className="md:w-[150px]"
                value={selectedStatus}
                onChange={setSelectedStatus}
                options={[
                  { value: "ALL", label: "All Statuses" },
                  { value: "APPROVED", label: "Approved" },
                  { value: "PENDING", label: "Pending Review" },
                  { value: NEEDS_FIX, label: "Rejected or paused" },
                  { value: "REJECTED", label: "Rejected" },
                  { value: "PAUSED", label: "Paused" },
                  { value: "DISABLED", label: "Turned off" },
                  { value: "ARCHIVED", label: "Archived" },
                  { value: "DELETED", label: "Deleted" },
                ]}
              />
              <Select
                size="sm"
                aria-label="Filter by language"
                className="md:w-[155px]"
                value={selectedLanguage}
                onChange={setSelectedLanguage}
                options={[{ value: "ALL", label: "All Languages" }, ...languageChoices]}
              />
              <Select
                size="sm"
                aria-label="Filter by where it is used"
                className="md:w-[150px]"
                value={selectedUsedIn}
                onChange={setSelectedUsedIn}
                options={[
                  { value: "ALL", label: "Used in: All" },
                  { value: "NONE", label: "Used in: Not used yet" },
                  ...usedInChoices.map((o) => ({ value: o.value, label: `Used in: ${o.label}` })),
                ]}
              />
            </div>

            <div className="ml-auto flex shrink-0 items-center gap-2">
              {hasFilters && (
                <button
                  onClick={clearFilters}
                  className="flex h-10 items-center gap-1 rounded-xl px-2.5 text-[12.5px] font-semibold text-[#475569] transition-colors hover:bg-red-50 hover:text-red-600"
                >
                  <X size={12} /> Clear
                </button>
              )}
              <div className="hidden h-10 items-center rounded-xl border border-[#e2e8f0] bg-white p-1 md:flex" role="group" aria-label="View">
                {([
                  { mode: "GRID", label: "Cards", icon: LayoutGrid },
                  { mode: "TABLE", label: "List", icon: List },
                ] as const).map((v) => (
                  <button
                    key={v.mode}
                    onClick={() => setViewMode(v.mode)}
                    aria-pressed={viewMode === v.mode}
                    className={`flex h-full items-center gap-1.5 rounded-lg px-3 text-[13px] font-semibold transition-colors ${
                      viewMode === v.mode ? "bg-primary text-white" : "text-ink hover:bg-[#f8fafc]"
                    }`}
                  >
                    <v.icon size={13} />
                    {v.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Scrollable Templates Content */}
      <div
        ref={scrollRef}
        onScroll={(e) => writeViewState({ scrollTop: e.currentTarget.scrollTop })}
        className="relative flex-1 overflow-y-auto min-h-0 pr-1 pb-6"
      >
        {loading ? (
        <AiraLoader inline className="min-h-[50vh]" />
      ) : filteredTemplates.length === 0 ? (
        <div className="card text-center py-16 rounded-3xl border border-border-subtle bg-white">
          <HelpCircle size={36} className="mx-auto text-ink-muted mb-3" />
          <p className="font-display font-semibold text-ink text-base">{hasFilters ? "No templates match these filters" : "No templates yet"}</p>
          <p className="font-body text-sm text-ink-muted mt-1 max-w-sm mx-auto leading-relaxed">
            {hasFilters
              ? "Try clearing a filter or searching for other words."
              : "Create a template and send it to Meta for approval, or sync to load the ones you already have."}
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {hasFilters ? (
              <button onClick={clearFilters} className="btn-ghost text-sm">Clear filters</button>
            ) : (
              <>
                <button onClick={handleSyncAll} disabled={!canManageTemplates} className="btn-ghost text-sm disabled:opacity-40">Sync from Meta</button>
                {canManageTemplates && (
                  <>
                    <button onClick={() => setAiOpen(true)} className="btn-ghost text-sm inline-flex items-center gap-1.5"><Sparkles size={14} /> Write with AI</button>
                    <Link href="/dashboard/templates/new" className="btn-primary text-sm px-5 py-2">Create Template</Link>
                  </>
                )}
              </>
            )}
          </div>
        </div>
      ) : viewMode === "GRID" ? (
        <>
          {/* Phone: compact rows */}
          <div className="space-y-2.5 md:hidden">
            {filteredTemplates.map((t) => (
              <TemplateRow key={t.id} template={t} usage={usage[t.id]} onOpen={setSelectedTemplate} />
            ))}
          </div>
          {/* Laptop and up: every card the same size */}
          <div className="hidden gap-4 md:grid md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredTemplates.map((t) => (
              <TemplateCard
                key={t.id}
                template={t}
                usage={usage[t.id]}
                usageReady={usageReady}
                canFix={canManageTemplates}
                syncing={syncingId === t.id}
                onPreview={setSelectedTemplate}
                onEdit={(tmpl) => router.push(`/dashboard/templates/${tmpl.id}`)}
                onDelete={canManageTemplates ? (tmpl) => handleDelete(tmpl.id) : undefined}
                onSync={canManageTemplates ? (tmpl) => handleSyncSingle(tmpl.id) : undefined}
                onVariations={canManageTemplates ? (tmpl) => openVariations(tmpl.id) : undefined}
                onSend={(tmpl) => router.push(`/dashboard/outbound-leads?template=${encodeURIComponent(tmpl.name)}`)}
                onDuplicate={canManageTemplates ? (tmpl) => openBuilderWith(prefillFromTemplate(tmpl)) : undefined}
                onMakeUtility={
                  canManageTemplates
                    ? (tmpl) => openBuilderWith(prefillFromTemplate(tmpl, { category: "UTILITY", suffix: "utility", source: `Utility copy of ${tmpl.name}. Send it to Meta, then switch the staff alert to it.` }))
                    : undefined
                }
              />
            ))}
          </div>
        </>
      ) : (
        /* Table View */
        <div className="bg-white border border-border-subtle rounded-2xl overflow-hidden shadow-sm">
          <div className="space-y-3 p-3 md:hidden">
            {filteredTemplates.map((t) => {
              const statusColors = STATUS_COLORS[t.status] || { bg: "bg-gray-100", text: "text-gray-600", dot: "bg-gray-400" };
              return (
                <div key={t.id} className="rounded-2xl border border-border-subtle bg-white p-4 shadow-sm" onClick={() => setSelectedTemplate(t)}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-sm font-semibold text-ink">{t.name}</p>
                      <p className="mt-1 text-xs text-ink-secondary">
                        {t.category} · {LANGUAGES.find((l) => l.code === t.language)?.label || t.language}
                      </p>
                      <div className="mt-2" onClick={(e) => e.stopPropagation()}>
                        <AiraId code={t.short_code} size="lg" />
                      </div>
                    </div>
                    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 font-label text-[10px] font-semibold ${statusColors.bg} ${statusColors.text}`}>
                      <span className={`h-1 w-1 rounded-full ${statusColors.dot}`} />
                      {t.status}
                    </span>
                  </div>
                  <TemplateNotes template={t} usage={usage[t.id]} usageReady={usageReady} canFix={canManageTemplates} className="mt-3" />
                  <div className="mt-4 flex flex-wrap justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => setSelectedTemplate(t)} className="rounded-lg bg-surface-subtle p-2 text-ink-muted hover:text-ink" title="View Preview"><Eye size={14} /></button>
                    {canManageTemplates && <button onClick={(e) => handleSyncSingle(t.id, e)} disabled={syncingId === t.id} className="rounded-lg bg-surface-subtle p-2 text-ink-muted hover:text-ink disabled:opacity-50" title="Sync Status"><RefreshCw size={14} className={syncingId === t.id ? "animate-spin" : ""} /></button>}
                    {canManageTemplates && <button onClick={(e) => openVariationsModal(t.id, e)} className="rounded-lg bg-primary-50 p-2 text-primary-600" title="Rotate Variations"><Shuffle size={14} /></button>}
                    <button onClick={() => router.push(`/dashboard/templates/${t.id}`)} className="rounded-lg bg-emerald-50 p-2 text-emerald-600" title="Open Detail/Editor"><ChevronRight size={14} /></button>
                    {canManageTemplates && <button onClick={(e) => handleDelete(t.id, e)} className="rounded-lg bg-red-50 p-2 text-red-500" title="Delete"><Trash2 size={14} /></button>}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left border-collapse">
              <thead className="sticky top-0 z-10 bg-surface-subtle">
                <tr className="bg-surface-subtle border-b border-border-subtle text-ink-muted text-[11px] font-bold uppercase tracking-wider">
                  <th className="px-5 py-3.5">Template Name</th>
                  <th className="px-5 py-3.5">Anril ID</th>
                  <th className="px-5 py-3.5">Category</th>
                  <th className="px-5 py-3.5">Language</th>
                  <th className="px-5 py-3.5">Status</th>
                  <th className="px-5 py-3.5">Used in / Why</th>
                  <th className="px-5 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle text-xs">
                {filteredTemplates.map((t) => {
                  const statusColors = STATUS_COLORS[t.status] || { bg: "bg-gray-100", text: "text-gray-600", dot: "bg-gray-400" };
                  return (
                    <tr
                      key={t.id}
                      onClick={() => setSelectedTemplate(t)}
                      className="hover:bg-surface-subtle/40 transition-colors cursor-pointer"
                    >
                      <td className="px-5 py-4 font-mono font-medium text-ink max-w-[280px]">
                        <span className="block truncate">{t.name}</span>
                      </td>
                      <td className="px-5 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <AiraId code={t.short_code} size="lg" />
                      </td>
                      <td className="px-5 py-4 text-ink-secondary">
                        {t.category}
                      </td>
                      <td className="px-5 py-4 text-ink-secondary">
                        {LANGUAGES.find((l) => l.code === t.language)?.label || t.language}
                      </td>
                      <td className="px-5 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-semibold ${statusColors.bg} ${statusColors.text}`}>
                          <span className={`w-1 h-1 rounded-full ${statusColors.dot}`} />
                          {t.status}
                        </span>
                      </td>
                      <td className="px-5 py-3 max-w-[300px]" onClick={(e) => e.stopPropagation()}>
                        <TemplateNotes template={t} usage={usage[t.id]} usageReady={usageReady} canFix={canManageTemplates} />
                      </td>
                      <td className="px-5 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => setSelectedTemplate(t)}
                            className="p-1.5 rounded-lg hover:bg-surface-subtle text-ink-muted hover:text-ink"
                            title="View Preview"
                          >
                            <Eye size={13} />
                          </button>
                          {canManageTemplates && (
                            <button
                              onClick={(e) => handleSyncSingle(t.id, e)}
                              disabled={syncingId === t.id}
                              className="p-1.5 rounded-lg hover:bg-surface-subtle text-ink-muted hover:text-ink disabled:opacity-50"
                              title="Sync Status"
                            >
                              <RefreshCw size={13} className={syncingId === t.id ? "animate-spin" : ""} />
                            </button>
                          )}
                          {canManageTemplates && (
                            <button
                              onClick={(e) => openVariationsModal(t.id, e)}
                              className="p-1.5 rounded-lg hover:bg-primary-50 text-ink-muted hover:text-primary-600"
                              title="Rotate Variations"
                            >
                              <Shuffle size={13} />
                            </button>
                          )}
                          <button
                            onClick={() => router.push(`/dashboard/templates/${t.id}`)}
                            className="p-1.5 rounded-lg hover:bg-emerald-50 text-ink-muted hover:text-emerald-600"
                            title="Open Detail/Editor"
                          >
                            <ChevronRight size={13} />
                          </button>
                          {canManageTemplates && (
                            <button
                              onClick={(e) => handleDelete(t.id, e)}
                              className="p-1.5 rounded-lg hover:bg-red-50 text-ink-muted hover:text-red-500"
                              title="Delete"
                            >
                              <Trash2 size={13} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </div>

      <ExcelPanel
        open={excelOpen}
        onClose={() => setExcelOpen(false)}
        totalCount={templates.length}
        canManage={canManageTemplates}
        loadAll={loadAllForExcel}
        onSubmitted={loadTemplates}
      />

      <AiDraftDialog
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        onDrafted={(p) => {
          setAiOpen(false);
          openBuilderWith(p);
        }}
      />

      {/* ── View Detail Drawer/Modal ─────────────────────────────────────────── */}
      {selectedTemplate && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-dialog flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-4xl overflow-hidden flex flex-col max-h-[85vh] animate-slide-up">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-5 border-b border-border-subtle bg-surface-subtle">
              <div className="min-w-0">
                <p className="font-body text-[10px] text-ink-muted uppercase font-bold tracking-wider">Template Detail</p>
                <h2 className="font-mono text-sm font-semibold text-ink truncate max-w-lg mt-0.5">{selectedTemplate.name}</h2>
              </div>
              <button
                onClick={() => setSelectedTemplate(null)}
                className="p-2 rounded-xl hover:bg-white/80 text-ink-muted hover:text-ink transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
              {/* Left Column: Metadata */}
              <div className="md:col-span-6 space-y-4">
                {selectedTemplate.short_code && (
                  <div className="flex items-center justify-between gap-4 rounded-2xl border border-primary-200 bg-primary-50/60 p-4">
                    <div className="min-w-0">
                      <p className="font-body text-[10px] text-primary-700 uppercase font-bold tracking-wider">Anril ID</p>
                      <p className="font-body text-xs text-ink-secondary mt-0.5">
                        Paste this number in adminweb → WhatsApp Templates to send this template from AstroTamil.
                      </p>
                    </div>
                    <AiraId code={selectedTemplate.short_code} size="lg" className="shrink-0" />
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4 bg-surface-subtle/40 p-4 rounded-2xl border border-border-subtle">
                  <div>
                    <p className="font-body text-[10px] text-ink-muted uppercase font-bold tracking-wider">Category</p>
                    <p className="font-body text-xs font-semibold text-ink mt-0.5">{selectedTemplate.category}</p>
                  </div>
                  <div>
                    <p className="font-body text-[10px] text-ink-muted uppercase font-bold tracking-wider">Language</p>
                    <p className="font-body text-xs font-semibold text-ink mt-0.5">
                      {LANGUAGES.find((l) => l.code === selectedTemplate.language)?.label || selectedTemplate.language}
                    </p>
                  </div>
                  <div>
                    <p className="font-body text-[10px] text-ink-muted uppercase font-bold tracking-wider">Meta ID</p>
                    <p className="font-mono text-[10px] font-semibold text-ink truncate mt-0.5 select-all">
                      {selectedTemplate.meta_template_id || "None"}
                    </p>
                  </div>
                  <div>
                    <p className="font-body text-[10px] text-ink-muted uppercase font-bold tracking-wider">Status</p>
                    <p className="font-body text-xs font-semibold text-ink mt-0.5">{selectedTemplate.status}</p>
                  </div>
                </div>

                {statusNote(selectedTemplate) && (
                  <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700">
                    <p className="font-semibold mb-0.5">
                      {selectedTemplate.status === "PAUSED" ? "Why Meta paused it" : selectedTemplate.status === "REJECTED" ? "Why Meta rejected it" : "What Meta did"}
                    </p>
                    <p className="leading-relaxed">{statusNote(selectedTemplate)?.text}</p>
                  </div>
                )}

                <div className="space-y-2">
                  <h3 className="font-body text-xs font-bold text-ink uppercase tracking-wider">Configuration</h3>
                  {selectedTemplate.header_text && (
                    <div>
                      <p className="font-body text-[10px] text-ink-muted">Header Text</p>
                      <p className="font-body text-xs text-ink">{selectedTemplate.header_text}</p>
                    </div>
                  )}
                  {selectedTemplate.footer_text && (
                    <div>
                      <p className="font-body text-[10px] text-ink-muted">Footer Text</p>
                      <p className="font-body text-xs text-ink-muted">{selectedTemplate.footer_text}</p>
                    </div>
                  )}
                  <div>
                    <p className="font-body text-[10px] text-ink-muted">Body Text</p>
                    <p className="font-body text-xs text-ink whitespace-pre-wrap leading-relaxed select-all">
                      {selectedTemplate.body_text}
                    </p>
                  </div>
                </div>
              </div>

              {/* Right Column: Live Preview */}
              <div className="md:col-span-6 space-y-3">
                <label className="font-body text-xs font-bold text-ink uppercase tracking-wider block">Live Message Preview</label>
                <WhatsAppPreview
                  headerType={selectedTemplate.header_media_type as "NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT" | undefined}
                  headerText={selectedTemplate.header_text || undefined}
                  headerMediaUrl={selectedTemplate.header_media_url || undefined}
                  bodyText={selectedTemplate.body_text}
                  footerText={selectedTemplate.footer_text || undefined}
                  buttons={selectedTemplate.buttons?.map((b) => ({
                    type: b.type,
                    text: b.type === "ONE_TAP" ? (b.autofill_text || "Autofill") : b.text,
                    url: b.url,
                    phone: b.phone,
                  })) || []}
                />
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-border-subtle bg-white flex items-center justify-end gap-2.5">
              <button onClick={() => setSelectedTemplate(null)} className="btn-ghost text-xs">Close</button>
              {canManageTemplates && (["APPROVED", "REJECTED", "PAUSED"].includes(selectedTemplate.status) || !selectedTemplate.meta_template_id)
                && !(selectedTemplate.status === "APPROVED" && selectedTemplate.edit_allowance && !selectedTemplate.edit_allowance.allowed) && (
                <button
                  onClick={() => {
                    setSelectedTemplate(null);
                    router.push(`/dashboard/templates/${selectedTemplate.id}`);
                  }}
                  className="btn-primary text-xs"
                >
                  {selectedTemplate.status === "APPROVED" ? "Edit" : "Edit and Resubmit"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Template Variations Modal ─────────────────────────────────────── */}
      {variationsModalId && (() => {
        const t = templates.find((x) => x.id === variationsModalId);
        return (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-dialog flex items-center justify-center p-4">
            <div className="bg-white rounded-3xl shadow-2xl w-full max-w-md p-6 animate-slide-up">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-xl bg-primary-50 flex items-center justify-center">
                    <Shuffle size={16} className="text-primary-600" />
                  </div>
                  <div>
                    <h2 className="font-display font-bold text-ink text-sm">Message Variations</h2>
                    {t && <p className="font-mono text-[10px] text-ink-muted mt-0.5 truncate max-w-[200px]">{t.name}</p>}
                  </div>
                </div>
                <button
                  onClick={() => {
                    setVariationsModalId(null);
                    setVariationsList([]);
                  }}
                  className="p-1.5 rounded-lg hover:bg-surface-subtle text-ink-muted"
                >
                  <X size={16} />
                </button>
              </div>

              <p className="font-body text-xs text-ink-muted leading-relaxed mb-4">
                Add other approved templates to rotate inside broadcasts. When sending messages, Anril will select randomly among variations.
              </p>

              {variationsLoading ? (
                <div className="space-y-2 mb-4">
                  <div className="h-8 rounded-lg bg-surface-subtle animate-pulse" />
                  <div className="h-8 rounded-lg bg-surface-subtle animate-pulse" />
                </div>
              ) : (
                <div className="space-y-4">
                  {variationsList.length === 0 ? (
                    <p className="text-xs text-ink-muted italic text-center py-4 bg-surface-subtle rounded-xl">No sibling variations configured.</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {variationsList.map((v) => (
                        <span key={v} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary-50 text-primary-700 text-xs font-mono font-medium">
                          {v}
                          {canManageTemplates && (
                            <button onClick={() => handleVariationRemove(v)} className="text-primary-400 hover:text-primary-700">
                              <X size={12} />
                            </button>
                          )}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Add Input */}
                  <div className="flex gap-2">
                    <input
                      value={newVariation}
                      onChange={(e) => setNewVariation(e.target.value)}
                      placeholder="Template name (exact case)"
                      className="input text-xs flex-1"
                    />
                    <button
                      onClick={handleVariationAdd}
                      disabled={!newVariation.trim() || !canManageTemplates}
                      className="btn-primary text-xs px-4 disabled:opacity-50"
                    >
                      Add
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
