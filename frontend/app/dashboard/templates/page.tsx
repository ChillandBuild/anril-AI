"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Plus,
  RefreshCw,
  Search,
  Filter,
  Grid,
  List,
  Shuffle,
  Trash2,
  Eye,
  Layers,
  ChevronRight,
  ChevronDown,
  Download,
  X,
  AlertCircle,
  HelpCircle,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { LANGUAGES, STATUS_COLORS } from "./types";
import type { Template } from "./types";
import TemplateCard from "./components/template-card";
import WhatsAppPreview from "./components/whatsapp-preview";
import { useAuthRole } from "../contexts/AuthRoleContext";
import AiraId from "./components/aira-id";

const TEMPLATES_SCROLL_KEY = "templates-list-scroll-y";

// Shared by the on-screen list and the CSV export so "download based on the filter" always matches what's visible.
function filterTemplates(list: Template[], searchQuery: string, category: string, status: string): Template[] {
  const q = searchQuery.trim().toLowerCase();
  return list.filter((t) => {
    const matchesSearch = !q ||
      t.name.toLowerCase().includes(q) ||
      t.body_text.toLowerCase().includes(q) ||
      (t.short_code ?? "").includes(q);
    const matchesCategory = category === "ALL" || t.category === category;
    const matchesStatus = status === "ALL" || t.status === status;
    return matchesSearch && matchesCategory && matchesStatus;
  });
}

function csvEscape(value: string): string {
  return `"${(value ?? "").replace(/"/g, '""')}"`;
}

// Everything a template can carry, flattened into one readable cell.
function buildTemplateContent(t: Template): string {
  const parts: string[] = [];
  if (t.header_text) {
    parts.push(`Header: ${t.header_text}`);
  } else if (t.header_media_type && t.header_media_type !== "NONE") {
    parts.push(`Header: [${t.header_media_type}]`);
  }
  parts.push(`Body: ${t.body_text}`);
  if (t.footer_text) parts.push(`Footer: ${t.footer_text}`);
  if (t.buttons && t.buttons.length > 0) {
    const buttonsStr = t.buttons.map((b) => {
      if (b.type === "URL") return `URL: ${b.text} (${b.url || ""})`;
      if (b.type === "PHONE_NUMBER") return `Call: ${b.text} (${b.phone || ""})`;
      if (b.type === "ONE_TAP") return `OTP Autofill: ${b.autofill_text || b.text}`;
      if (b.type === "COPY_CODE") return `Copy Code: ${b.text}`;
      return `${b.type}: ${b.text}`;
    }).join(" | ");
    parts.push(`Buttons: ${buttonsStr}`);
  }
  if (t.carousel_cards && t.carousel_cards.length > 0) {
    t.carousel_cards.forEach((c, i) => {
      parts.push(`Carousel Card ${i + 1}: ${c.body_text}`);
    });
  }
  return parts.join("\n");
}

export default function TemplatesPage() {
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManageTemplates = role === "owner" || permissions.includes("templates.manage");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Sync / Action states
  const [syncing, setSyncing] = useState(false);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Preserve scroll position across navigating into a template and back
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const scrollSaveFrame = useRef<number | null>(null);
  function handleListScroll() {
    if (scrollSaveFrame.current !== null) return;
    scrollSaveFrame.current = requestAnimationFrame(() => {
      if (scrollContainerRef.current) {
        sessionStorage.setItem(TEMPLATES_SCROLL_KEY, String(scrollContainerRef.current.scrollTop));
      }
      scrollSaveFrame.current = null;
    });
  }

  // Search & Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");
  const [selectedStatus, setSelectedStatus] = useState<string>("ALL");
  const [viewMode, setViewMode] = useState<"GRID" | "TABLE">("GRID");

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
  }

  useEffect(() => {
    loadTemplates();
  }, []);

  // Restore list scroll position once templates have rendered after mount
  useEffect(() => {
    if (!loading && scrollContainerRef.current) {
      const saved = sessionStorage.getItem(TEMPLATES_SCROLL_KEY);
      if (saved) scrollContainerRef.current.scrollTop = parseInt(saved, 10);
    }
  }, [loading]);

  // Export the currently filtered list as CSV, re-fetching first so an approval since page-load is reflected
  async function handleExportCsv() {
    setExporting(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/`, { headers: authHeaders });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      const data = await res.json();
      const freshTemplates: Template[] = data.data || [];
      const rows = filterTemplates(freshTemplates, searchQuery, selectedCategory, selectedStatus);

      const header = ["Template Name", "Anril ID", "Content", "Category", "Language", "Status"];
      const csvLines = [header, ...rows.map((t) => [
        t.name,
        t.short_code || "",
        buildTemplateContent(t),
        t.category,
        LANGUAGES.find((l) => l.code === t.language)?.label || t.language,
        t.status,
      ])].map((row) => row.map(csvEscape).join(","));

      const blob = new Blob(["﻿" + csvLines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `whatsapp-templates-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to export CSV");
    } finally {
      setExporting(false);
    }
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
  async function openVariationsModal(id: string, e: React.MouseEvent) {
    e.stopPropagation();
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
  const filteredTemplates = filterTemplates(templates, searchQuery, selectedCategory, selectedStatus);

  const hasFilters = !!(searchQuery || selectedCategory !== "ALL" || selectedStatus !== "ALL");
  const activeFilterCount = [searchQuery, selectedCategory !== "ALL" ? selectedCategory : "", selectedStatus !== "ALL" ? selectedStatus : ""].filter(Boolean).length;

  // Calculate statistics
  const countApproved = templates.filter((t) => t.status === "APPROVED").length;
  const countPending = templates.filter((t) => t.status === "PENDING").length;
  const countRejected = templates.filter((t) => t.status === "REJECTED" || t.status === "PAUSED").length;

  return (
    <div className="flex flex-col min-w-0 h-[calc(100dvh-11.5rem)] md:h-[calc(100dvh-7.5rem)] overflow-hidden">
      {/* Top Locked Section: Stats, Actions & Filters */}
      <div className="shrink-0 space-y-4 pb-4">
        {/* Stats and Action Bar */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 md:gap-4">
        {[
          { label: "Approved Templates", count: countApproved, color: "#10b981", tone: "border-t-emerald-400" },
          { label: "Pending Review", count: countPending, color: "#f59e0b", tone: "border-t-amber-400" },
          { label: "Rejected / Paused", count: countRejected, color: "#ef4444", tone: "border-t-rose-400" },
        ].map((s) => (
          <div
            key={s.label}
            className={`flex items-center gap-3 rounded-2xl border border-border border-t-4 bg-white p-4 shadow-sm sm:gap-4 ${s.tone}`}
            style={{ borderTopColor: s.color, borderTopWidth: "4px", borderTopStyle: "solid" }}
          >
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-white text-lg font-bold sm:h-12 sm:w-12" style={{ color: s.color }}>
              {s.count}
            </div>
            <div className="min-w-0">
              <p className="font-body text-xs text-ink-muted uppercase tracking-wider font-bold">{s.label}</p>
              <p className="font-display font-semibold text-ink text-sm mt-0.5">templates loaded</p>
            </div>
          </div>
        ))}

        {/* Actions Column */}
        <div className="flex flex-col justify-between gap-2 p-1">
          <div className="flex gap-2">
            <button
              onClick={handleSyncAll}
              disabled={syncing || !canManageTemplates}
              title={canManageTemplates ? "Sync from Meta" : "Read-only role: sync is disabled"}
              className="flex-1 px-3 py-2 bg-white border border-[#e2e8f0] hover:bg-[#f1f5f9] text-[#0A1528] rounded-xl font-label text-xs font-bold transition-all shadow-sm flex items-center justify-center gap-1.5"
            >
              <RefreshCw size={12} className={syncing ? "animate-spin" : ""} />
              {syncing ? "Syncing..." : "Sync"}
            </button>
            <Link
              href="/dashboard/templates/carousel"
              className="flex-1 px-3 py-2 bg-white border border-[#e2e8f0] hover:bg-[#f1f5f9] text-[#0A1528] rounded-xl font-label text-xs font-bold transition-all shadow-sm flex items-center justify-center gap-1.5"
            >
              <Layers size={12} />
              Carousel
            </Link>
            <button
              onClick={handleExportCsv}
              disabled={exporting || filteredTemplates.length === 0}
              title="Download the currently filtered templates as CSV"
              className="flex-1 px-3 py-2 bg-white border border-[#e2e8f0] hover:bg-[#f1f5f9] text-[#0A1528] rounded-xl font-label text-xs font-bold transition-all shadow-sm flex items-center justify-center gap-1.5 disabled:opacity-50"
            >
              <Download size={12} className={exporting ? "animate-pulse" : ""} />
              {exporting ? "Exporting..." : "CSV"}
            </button>
          </div>
          <Link
            href="/dashboard/templates/new"
            className="w-full py-2.5 bg-primary hover:bg-primary/90 text-white rounded-xl font-label text-xs font-bold transition-all shadow-md shadow-primary-200 flex items-center justify-center gap-1.5"
          >
            <Plus size={14} />
            Create Template
          </Link>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-xl text-sm flex items-center gap-2 animate-slide-up">
          <AlertCircle size={15} />
          <span>{error}</span>
        </div>
      )}

      {/* Filter Results Panel */}
      <div className="rounded-2xl border border-surface-mid/80 bg-white/95 p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2.5 lg:flex-nowrap">
          <div className="flex shrink-0 items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-50 text-primary-700 ring-1 ring-primary-100">
              <Filter size={14} />
            </span>
            <div className="hidden leading-tight sm:block">
              <span className="block font-label text-[13px] font-bold text-on-surface">Filter Results</span>
              <span className="block font-body text-[10px] text-on-surface-muted">
                {activeFilterCount > 0 ? `${activeFilterCount} active` : "All templates"}
              </span>
            </div>
          </div>

          <div className="relative min-w-[160px] flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search templates..."
              style={{ paddingLeft: "2rem", paddingRight: searchQuery ? "1.75rem" : "0.75rem" }}
              className="h-9 w-full rounded-xl border border-surface-mid bg-white font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] hover:text-[#1e293b] transition-colors"
              >
                <X size={12} />
              </button>
            )}
          </div>

          <div className="relative w-[130px] shrink-0 sm:w-[150px]">
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="h-9 w-full cursor-pointer appearance-none rounded-xl border border-surface-mid bg-white px-3 pr-7 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
            >
              <option value="ALL">All Types</option>
              <option value="MARKETING">Marketing</option>
              <option value="UTILITY">Utility</option>
              <option value="AUTHENTICATION">Authentication</option>
            </select>
            <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] pointer-events-none" />
          </div>

          <div className="relative w-[130px] shrink-0 sm:w-[150px]">
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="h-9 w-full cursor-pointer appearance-none rounded-xl border border-surface-mid bg-white px-3 pr-7 font-body text-xs font-semibold text-on-surface shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] transition-colors hover:border-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-200"
            >
              <option value="ALL">All Statuses</option>
              <option value="APPROVED">Approved</option>
              <option value="PENDING">Pending</option>
              <option value="REJECTED">Rejected</option>
              <option value="PAUSED">Paused</option>
              <option value="DISABLED">Disabled</option>
              <option value="ARCHIVED">Archived</option>
              <option value="DELETED">Deleted</option>
            </select>
            <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] pointer-events-none" />
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {hasFilters && (
              <button
                onClick={() => {
                  setSearchQuery("");
                  setSelectedCategory("ALL");
                  setSelectedStatus("ALL");
                }}
                className="flex h-9 items-center gap-1 rounded-full border border-transparent px-2.5 text-[11px] font-semibold text-[#475569] transition-colors hover:border-red-100 hover:bg-red-50 hover:text-red-600"
              >
                <X size={11} /> Clear
              </button>
            )}
            {/* Grid/Table Toggle */}
            <div className="flex h-9 items-center gap-0.5 rounded-lg border border-surface-mid bg-[#f8f5ef] p-0.5">
              <button
                onClick={() => setViewMode("GRID")}
                aria-label="Grid view"
                title="Grid view"
                className={`flex h-full items-center justify-center rounded-md px-2 transition-all ${
                  viewMode === "GRID" ? "bg-white text-primary shadow-sm" : "text-[#94a3b8] hover:text-[#1e293b]"
                }`}
              >
                <Grid size={13} />
              </button>
              <button
                onClick={() => setViewMode("TABLE")}
                aria-label="Table view"
                title="Table view"
                className={`flex h-full items-center justify-center rounded-md px-2 transition-all ${
                  viewMode === "TABLE" ? "bg-white text-primary shadow-sm" : "text-[#94a3b8] hover:text-[#1e293b]"
                }`}
              >
                <List size={13} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Scrollable Templates Content */}
      <div ref={scrollContainerRef} onScroll={handleListScroll} className="flex-1 overflow-y-auto min-h-0 pr-1 pb-6">
        {/* Main Content Area */}
        {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="card h-64 border border-border-subtle rounded-2xl animate-pulse bg-surface-subtle" />
          ))}
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="card text-center py-16 rounded-3xl border border-border-subtle bg-white">
          <HelpCircle size={36} className="mx-auto text-ink-muted mb-3" />
          <p className="font-display font-semibold text-ink text-base">No Templates Found</p>
          <p className="font-body text-xs text-ink-muted mt-1 max-w-xs mx-auto leading-relaxed">
            Create a new template to submit it to WhatsApp, or sync with Meta to load your existing structures.
          </p>
          <div className="mt-6 flex items-center justify-center gap-3">
            <button onClick={handleSyncAll} disabled={!canManageTemplates} className="btn-ghost text-xs disabled:opacity-40">Sync from Meta</button>
            {canManageTemplates && (
              <Link href="/dashboard/templates/new" className="btn-primary text-xs px-5 py-2">
                New Template
              </Link>
            )}
          </div>
        </div>
      ) : viewMode === "GRID" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredTemplates.map((t) => (
            <TemplateCard
              key={t.id}
              template={t}
              onEdit={(tmpl) => router.push(`/dashboard/templates/${tmpl.id}`)}
              onDelete={canManageTemplates ? (tmpl) => handleDelete(tmpl.id) : undefined}
              onSync={canManageTemplates ? (tmpl) => handleSyncSingle(tmpl.id) : undefined}
              onSend={(tmpl) => router.push(`/dashboard/outbound-leads?template=${encodeURIComponent(tmpl.name)}`)}
              onDuplicate={canManageTemplates ? (tmpl) => {
                // Quick duplicate to builder
                router.push(`/dashboard/templates/new?duplicate=${tmpl.id}`);
              } : undefined}
            />
          ))}
        </div>
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
    </div>

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

                {selectedTemplate.rejection_reason && (
                  <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700">
                    <p className="font-semibold mb-0.5">WhatsApp Rejection Reason:</p>
                    <p className="leading-relaxed">{selectedTemplate.rejection_reason}</p>
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
                  className="btn-primary text-xs bg-emerald-600 hover:bg-emerald-700"
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
