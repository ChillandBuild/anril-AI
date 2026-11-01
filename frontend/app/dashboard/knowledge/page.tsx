"use client";

import { toast } from "sonner";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Search, Plus, Trash2, XCircle,
  Upload, FileText, Loader2, AlertCircle,
  Save, Eye, Download, X,
  HardDrive, Check, Copy,
  Sparkles, LayoutGrid, List,
  FileSpreadsheet, FileCode, Image as ImageIcon,
  Tag, Shield, BookOpen, ArrowRight, Lightbulb,
  ClipboardCheck, History, RefreshCw, Pencil,
  AlertTriangle
} from "lucide-react";
import { api, API_URL, getAuthHeaders, KnowledgeDocContent } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AiraLoader } from "@/components/AiraLoader";
import { SectionLoadGate } from "../settings/SettingsSection";
import { usePolling } from "@/hooks/usePolling";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { useRouter, useSearchParams } from "next/navigation";
import { SwitchPill } from "@/components/ui/controls";
import { ConflictsLink } from "@/components/brain/ConflictsLink";
import { announceApprovalsChanged } from "@/components/brain/approvalsEvent";
import KnowledgeReviewModal from "./KnowledgeReviewModal";
import KnowledgeHistoryModal from "./KnowledgeHistoryModal";
import DeleteDocumentModal from "./DeleteDocumentModal";
import ProfileSectionsEditor from "./ProfileSectionsEditor";
import { AutoGrowTextarea } from "./useAutoGrow";
import KitStarter from "./KitStarter";
import ReadinessLine from "./ReadinessLine";
import KnowledgeGapAnswerForm from "./KnowledgeGapAnswerForm";

// ─── Interfaces & Types ───────────────────────────────────────────────────────

interface KnowledgeDoc {
  id: string;
  name: string;
  size_bytes: number;
  file_type: string;
  status: string;
  created_at: string;
  chunk_count?: number;
  error_message?: string | null;
  campaign_tag_id?: string | null;
  /** null = uploaded before auto-sort; Anril still reads the whole file. */
  sorted_at?: string | null;
  sort_state?: "sorting" | "review" | "failed" | null;
  has_pending_review?: boolean;
  /** False when Anril can't run a vector search over this file -- it falls back
   *  to reading the whole file on every reply instead. */
  searchable?: boolean;
  search_issue?: null | "no_jina_key" | "not_indexed";
}

interface CampaignTag {
  id: string;
  name: string;
  color?: string;
}

// ─── Document status (Knowledge Auto-Sort) ────────────────────────────────────
// A file is "live" once its sort was applied; "not sorted" files predate auto-sort
// and keep working, but Anril reads all of their text, rules included.

type DocStatus = "sorting" | "review" | "live" | "unsorted" | "sort_failed" | "failed";

function docStatus(doc: KnowledgeDoc): DocStatus {
  if (doc.status === "processing" || doc.sort_state === "sorting") return "sorting";
  if (doc.status === "review_pending" || doc.has_pending_review) return "review";
  if (doc.status === "failed") return "failed";
  if (doc.sort_state === "failed") return "sort_failed";
  return doc.sorted_at ? "live" : "unsorted";
}

const DOC_STATUS_STYLE: Record<DocStatus, { label: string; className: string; title?: string }> = {
  sorting: { label: "Sorting", className: "bg-amber-50 text-amber-700 border-amber-200" },
  review: { label: "Review ready", className: "bg-primary-50 text-primary-700 border-primary-200" },
  live: { label: "Live", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  unsorted: {
    label: "Not sorted",
    className: "bg-slate-50 text-slate-600 border-slate-200",
    title: "Uploaded before auto-sort. Anril reads the whole file, rules included. Sort it to split out the rules.",
  },
  sort_failed: { label: "Sort failed", className: "bg-red-50 text-red-700 border-red-200" },
  failed: { label: "Failed", className: "bg-red-50 text-red-700 border-red-200" },
};

// A "live" (indexed) file that Anril still can't vector-search -- either this
// account has no Jina key, or the file hasn't gone through indexing yet. The
// text stays visible (not colour-only) since this is a real functional gap,
// not just a status flavor.
const NOT_SEARCHABLE_TITLE: Record<"no_jina_key" | "not_indexed", string> = {
  no_jina_key:
    "Anril can't search this file because no Jina key is set for this account. Ask your Anril operator to add one. Until then, Anril reads the whole file on every reply, which stops working well once your files get long.",
  not_indexed: "This file hasn't been prepared for search yet. Try Re-sort.",
};

function DocStatusBadge({ doc, className }: { doc: KnowledgeDoc; className?: string }) {
  const status = docStatus(doc);
  const notSearchable = status === "live" && doc.searchable === false;
  const style = notSearchable
    ? {
        label: "Not searchable",
        className: "bg-amber-50 text-amber-700 border-amber-200",
        title: NOT_SEARCHABLE_TITLE[doc.search_issue === "no_jina_key" ? "no_jina_key" : "not_indexed"],
      }
    : DOC_STATUS_STYLE[status];
  return (
    <div
      title={style.title}
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-label font-bold uppercase border",
        style.className,
        className
      )}
    >
      {notSearchable ? (
        <AlertTriangle size={11} />
      ) : status === "sorting" ? (
        <Loader2 size={11} className="animate-spin" />
      ) : status === "review" ? (
        <ClipboardCheck size={11} />
      ) : status === "failed" || status === "sort_failed" ? (
        <XCircle size={11} />
      ) : (
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full",
            status === "live" ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
          )}
        />
      )}
      <span>{style.label}</span>
    </div>
  );
}

interface FileTypeMeta {
  label: string;
  ext: string;
  badgeBg: string;
  badgeText: string;
  badgeBorder: string;
  iconBg: string;
  iconColor: string;
  category: "pdf" | "word" | "spreadsheet" | "presentation" | "text" | "image" | "other";
}

// ─── File Formatting Helpers ──────────────────────────────────────────────────

function getFileTypeMeta(fileType: string, fileName: string): FileTypeMeta {
  const lowerName = fileName.toLowerCase();
  const lowerType = (fileType || "").toLowerCase();

  if (lowerName.endsWith(".pdf") || lowerType.includes("pdf")) {
    return {
      label: "PDF",
      ext: ".pdf",
      badgeBg: "bg-red-50",
      badgeText: "text-red-700",
      badgeBorder: "border-red-200",
      iconBg: "bg-red-500/10",
      iconColor: "text-red-600",
      category: "pdf",
    };
  }
  if (
    lowerName.endsWith(".docx") ||
    lowerName.endsWith(".doc") ||
    lowerType.includes("word") ||
    lowerType.includes("wordprocessingml")
  ) {
    return {
      label: "Word",
      ext: lowerName.endsWith(".doc") ? ".doc" : ".docx",
      badgeBg: "bg-blue-50",
      badgeText: "text-blue-700",
      badgeBorder: "border-blue-200",
      iconBg: "bg-blue-500/10",
      iconColor: "text-blue-600",
      category: "word",
    };
  }
  if (
    lowerName.endsWith(".xlsx") ||
    lowerName.endsWith(".xls") ||
    lowerType.includes("spreadsheet") ||
    lowerType.includes("excel")
  ) {
    return {
      label: "Excel",
      ext: lowerName.endsWith(".xls") ? ".xls" : ".xlsx",
      badgeBg: "bg-emerald-50",
      badgeText: "text-emerald-700",
      badgeBorder: "border-emerald-200",
      iconBg: "bg-emerald-500/10",
      iconColor: "text-emerald-600",
      category: "spreadsheet",
    };
  }
  if (lowerName.endsWith(".csv") || lowerType.includes("csv")) {
    return {
      label: "CSV",
      ext: ".csv",
      badgeBg: "bg-teal-50",
      badgeText: "text-teal-700",
      badgeBorder: "border-teal-200",
      iconBg: "bg-teal-500/10",
      iconColor: "text-teal-600",
      category: "spreadsheet",
    };
  }
  if (
    lowerName.endsWith(".pptx") ||
    lowerName.endsWith(".ppt") ||
    lowerType.includes("presentation") ||
    lowerType.includes("powerpoint")
  ) {
    return {
      label: "PowerPoint",
      ext: lowerName.endsWith(".ppt") ? ".ppt" : ".pptx",
      badgeBg: "bg-amber-50",
      badgeText: "text-amber-700",
      badgeBorder: "border-amber-200",
      iconBg: "bg-amber-500/10",
      iconColor: "text-amber-600",
      category: "presentation",
    };
  }
  if (
    lowerName.endsWith(".txt") ||
    lowerName.endsWith(".md") ||
    lowerName.endsWith(".markdown") ||
    lowerType.includes("text/")
  ) {
    return {
      label: lowerName.endsWith(".md") || lowerName.endsWith(".markdown") ? "Markdown" : "Text",
      ext: lowerName.endsWith(".md") ? ".md" : ".txt",
      badgeBg: "bg-stone-100",
      badgeText: "text-stone-700",
      badgeBorder: "border-stone-200",
      iconBg: "bg-stone-500/10",
      iconColor: "text-stone-600",
      category: "text",
    };
  }
  if (lowerType.startsWith("image/") || /\.(png|jpe?g|webp|gif|svg)$/i.test(lowerName)) {
    return {
      label: "Image",
      ext: lowerName.match(/\.[0-9a-z]+$/i)?.[0] || ".img",
      badgeBg: "bg-primary-50",
      badgeText: "text-primary-700",
      badgeBorder: "border-primary-200",
      iconBg: "bg-primary-500/10",
      iconColor: "text-primary-600",
      category: "image",
    };
  }
  return {
    label: "Document",
    ext: lowerName.match(/\.[0-9a-z]+$/i)?.[0] || ".doc",
    badgeBg: "bg-surface-mid",
    badgeText: "text-on-surface-muted",
    badgeBorder: "border-surface-mid",
    iconBg: "bg-primary/10",
    iconColor: "text-primary",
    category: "other",
  };
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

// Values of the status filter that ?status= may preset.
const PRESETTABLE_STATUSES = ["all", "live", "unsorted", "review", "sorting", "failed"];

// ─── Component ────────────────────────────────────────────────────────────────

export default function KnowledgePage() {
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const canViewKnowledge =
    role === "owner" ||
    permissions.includes("knowledge.view") ||
    permissions.includes("knowledge.manage");
  const canManageKnowledge =
    role === "owner" || permissions.includes("knowledge.manage");
  // Only an owner can change the Description (ai_tune is owner-only); the review,
  // delete and history screens use this to explain why Apply is disabled.
  const isOwner = role === "owner";

  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [campaignFilter, setCampaignFilter] = useState<string>("all");
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");

  const router = useRouter();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  // Documents (RAG) is the default (2026-09-20): uploading is the job clients come
  // here for, and since the description gate was removed nothing has to happen
  // first. The Description is one click on, at `?tab=description`; `?tab=ai-tune`
  // is an old link that still lands there, and `?tab=documents` still works.
  // Flipping this back means changing four places: here, the pill array order in
  // AppHeader, its `isActive` derivation, and `getPageMeta()`'s tabLabel default.
  const tab = (rawTab === "description" || rawTab === "ai-tune"
    ? "description"
    : "documents") as "documents" | "description";

  // The hub links here with ?status=review to land on the files waiting for review.
  const presetStatus = searchParams.get("status");
  const gapQuestion = searchParams.get("question")?.trim().slice(0, 2000) ?? "";
  const requestedReviewId = searchParams.get("review");
  const openedReviewLink = useRef<string | null>(null);
  const uploadedDocumentId = searchParams.get("uploaded");
  useEffect(() => {
    if (presetStatus && PRESETTABLE_STATUSES.includes(presetStatus)) setStatusFilter(presetStatus);
  }, [presetStatus]);

  // Document Upload
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [campaignTags, setCampaignTags] = useState<CampaignTag[]>([]);
  const [selectedCampaignTag, setSelectedCampaignTag] = useState<string>("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Product Description & AI Tuning (savedDescription is used in Documents tab status row)
  const [savedDescription, setSavedDescription] = useState<string>("");


  const [scoringRubric, setScoringRubric] = useState<string>("");
  const [savedRubric, setSavedRubric] = useState<string>("");
  const [rubricSaving, setRubricSaving] = useState(false);
  const [rubricAutoUpdate, setRubricAutoUpdate] = useState(false);
  const [rubricToggleSaving, setRubricToggleSaving] = useState(false);
  // Description + rubric drive the upload gate on the Documents tab, so they are
  // fetched on mount rather than lazily when the Description tab opens.
  const [setupLoaded, setSetupLoaded] = useState(false);
  // The rubric box must not open empty after a failed load: saving it would
  // blank the tenant's real rubric.
  const [rubricLoadFailed, setRubricLoadFailed] = useState(false);

  // Document Viewer Modal
  const [viewingDoc, setViewingDoc] = useState<KnowledgeDocContent | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [viewerSearch, setViewerSearch] = useState("");
  const [copiedText, setCopiedText] = useState(false);

  // Delete (with a preview of what leaves the Description)
  const [deletingDoc, setDeletingDoc] = useState<KnowledgeDoc | null>(null);

  // Knowledge Auto-Sort
  const [reviewingDocId, setReviewingDocId] = useState<string | null>(null);
  const [historyTarget, setHistoryTarget] = useState<{
    kind: "description" | "facts";
    documentId?: string;
    title: string;
  } | null>(null);
  // "Does this replace an existing file?" -- "" means it's a new file.
  const [replaceTarget, setReplaceTarget] = useState<string>("");
  const [sameNamePrompt, setSameNamePrompt] = useState<{ file: File; existing: KnowledgeDoc } | null>(null);
  const [factsEditing, setFactsEditing] = useState(false);
  const [factsDraft, setFactsDraft] = useState("");
  const [factsSaving, setFactsSaving] = useState(false);

  // ─── Setup state (nothing here blocks an upload) ────────────────────────────
  // The 2026-09-18 pass removed the upload lock; 2026-09-20 removed the last block,
  // the review screen's refusal to apply a file that leaves the Description empty.
  // Both are warnings now: the Description box below carries the "not written yet"
  // pill, and the review screen warns before Apply. The rubric only scores leads and
  // is generated from the Description when missing, so it never blocked anything.
  //
  // `savedDescription` is only trustworthy for an owner: the whole ai_tune router is
  // owner-only, so `loadDescription()` swallows a 403 for a manager and leaves it "".
  // Anything that reasons about "is the Description empty" must be owner-gated, or it
  // tells managers their description is missing when it isn't -- which is why the
  // readiness line asks GET /knowledge/readiness instead.
  const hasRubric = savedRubric.trim().length > 0;
  const showStartHint = setupLoaded && canManageKnowledge && !hasRubric;
  const canUpload = canManageKnowledge && setupLoaded;

  // Re-check readiness whenever a file's status or the Description changes (the handover
  // wording is a Description section now).
  const readinessKey = [
    documents.map((d) => `${d.id}:${d.status}`).join(","),
    savedDescription,
  ].join("|");

  function goToDescription() {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", "description");
    router.replace(`/dashboard/knowledge?${params.toString()}`, { scroll: false });
  }

  useEffect(() => {
    loadData();
    api.knowledge
      .listCampaignTags()
      .then(setCampaignTags)
      .catch(() => {});
    // Both tabs need these: Description renders them, Documents gates uploading on them.
    Promise.all([loadDescription(), loadAiTuneSettings()]).finally(() =>
      setSetupLoaded(true)
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const hasProcessing = useMemo(
    () => documents.some((d) => docStatus(d) === "sorting"),
    [documents]
  );
  usePolling(loadDocuments, 5000, hasProcessing);

  useEffect(() => {
    if (!requestedReviewId || openedReviewLink.current === requestedReviewId) return;
    const requested = documents.find((document) => document.id === requestedReviewId);
    if (requested && docStatus(requested) === "review") {
      openedReviewLink.current = requestedReviewId;
      setReviewingDocId(requested.id);
    }
  }, [documents, requestedReviewId]);

  // Map campaign tags for fast lookup
  const tagMap = useMemo(() => {
    const map = new Map<string, CampaignTag>();
    campaignTags.forEach((t) => map.set(t.id, t));
    return map;
  }, [campaignTags]);

  // Document statistics
  const stats = useMemo(() => {
    const total = documents.length;
    const indexedDocs = documents.filter((d) => d.status === "indexed");
    // `searchable === undefined` means the API predates this field -- treat those
    // docs as searchable so older accounts don't suddenly show a false warning.
    const indexed = indexedDocs.filter((d) => d.searchable !== false).length;
    const notSearchable = indexedDocs.filter((d) => d.searchable === false).length;
    const processing = documents.filter((d) => docStatus(d) === "sorting").length;
    const review = documents.filter((d) => docStatus(d) === "review").length;
    const failed = documents.filter((d) => ["failed", "sort_failed"].includes(docStatus(d))).length;
    const totalBytes = documents.reduce((sum, d) => sum + (d.size_bytes || 0), 0);
    const scopedCount = documents.filter((d) => Boolean(d.campaign_tag_id)).length;
    return { total, indexed, notSearchable, processing, review, failed, totalBytes, scopedCount };
  }, [documents]);

  // Filtered documents
  const filteredDocs = useMemo(() => {
    return documents.filter((doc) => {
      // Text search
      if (search.trim()) {
        const q = search.toLowerCase();
        const matchesName = doc.name.toLowerCase().includes(q);
        const tag = doc.campaign_tag_id ? tagMap.get(doc.campaign_tag_id)?.name.toLowerCase() : "";
        if (!matchesName && !tag?.includes(q)) return false;
      }

      // Status filter ("failed" covers both a failed upload and a failed sort)
      if (statusFilter !== "all") {
        const status = docStatus(doc);
        const matches = statusFilter === "failed" ? status === "failed" || status === "sort_failed" : status === statusFilter;
        if (!matches) return false;
      }

      // Campaign filter
      if (campaignFilter === "global" && doc.campaign_tag_id) {
        return false;
      }
      if (campaignFilter !== "all" && campaignFilter !== "global" && doc.campaign_tag_id !== campaignFilter) {
        return false;
      }

      // Category filter
      if (categoryFilter !== "all") {
        const meta = getFileTypeMeta(doc.file_type, doc.name);
        if (meta.category !== categoryFilter) return false;
      }

      return true;
    });
  }, [documents, search, statusFilter, campaignFilter, categoryFilter, tagMap]);

  if (roleLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 size={24} className="animate-spin text-primary" />
      </div>
    );
  }

  if (!canViewKnowledge) {
    return (
      <div className="text-center py-20 bg-surface rounded-2xl border border-surface-mid p-8">
        <Shield size={32} className="mx-auto mb-3 text-on-surface-muted" />
        <h3 className="font-display font-bold text-on-surface text-base">Access Restricted</h3>
        <p className="text-on-surface-muted font-body text-sm mt-1">
          You do not have permission to view or manage the knowledge base.
        </p>
      </div>
    );
  }

  // ─── Data Loaders ─────────────────────────────────────────────────────────

  async function loadData() {
    setLoading(true);
    try {
      const docData = await api.knowledge.listDocuments();
      setDocuments(docData);
    } catch {
      // silent fail open
    } finally {
      setLoading(false);
    }
  }

  async function loadDocuments() {
    try {
      const docData = await api.knowledge.listDocuments();
      setDocuments(docData);
    } catch {}
  }

  async function loadDescription() {
    try {
      const d = await api.aiTune.description();
      setSavedDescription(d);
    } catch {}
  }

  async function loadAiTuneSettings() {
    setRubricLoadFailed(false);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/`, { headers: auth });
      if (!res.ok) {
        setRubricLoadFailed(true);
        return;
      }
      const data = await res.json();
      const settings: { key: string; display_value: string }[] = data.settings ?? [];
      const rubric = settings.find((s) => s.key === "scoring_rubric");
      if (rubric) {
        const val = rubric.display_value === "Not set" ? "" : rubric.display_value;
        setScoringRubric(val);
        setSavedRubric(val);
      }
      const auto = settings.find((s) => s.key === "rubric_auto_update");
      setRubricAutoUpdate(auto?.display_value === "true");
    } catch {
      setRubricLoadFailed(true);
    }
  }

  // ─── Upload Handlers ───────────────────────────────────────────────────────

  // replacesId: undefined = use the picker; null = explicitly a new file.
  async function processUpload(file: File, replacesId?: string | null) {
    if (!canManageKnowledge) {
      setUploadError("Read-only role: document upload is disabled.");
      return;
    }
    const target = replacesId === undefined ? replaceTarget || null : replacesId;
    // Same name, no replacement chosen: ask rather than silently keeping both
    // (spec §6.4 -- two versions of a price list would both be looked up).
    if (replacesId === undefined && !target) {
      const existing = documents.find((d) => d.name === file.name);
      if (existing) {
        setSameNamePrompt({ file, existing });
        return;
      }
    }
    setUploading(true);
    setUploadError(null);
    try {
      await api.knowledge.uploadDocument(file, selectedCampaignTag || null, target);
      toast.success(`"${file.name}" uploaded. Anril is sorting it — you'll review the result before anything changes.`);
      setReplaceTarget("");
      await loadDocuments();
    } catch (e) {
      const message =
        e instanceof Error && e.message && e.message !== "Upload failed"
          ? e.message
          : "Upload failed. Please check file format and try again.";
      setUploadError(message);
      toast.error(message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      processUpload(file);
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (!uploading && canUpload) {
      setIsDragging(true);
    }
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (uploading || !canUpload) return;
    const file = e.dataTransfer.files?.[0];
    if (file) {
      processUpload(file);
    }
  }

  // ─── Delete Handlers ───────────────────────────────────────────────────────

  // After anything that may have rewritten the Description (apply, delete, restore):
  // reload it, and the rubric a moment later in case it was regenerated.
  function refreshAfterDescriptionChange() {
    loadDescription();
    setTimeout(loadAiTuneSettings, 4000);
  }

  async function resortDocument(docId: string) {
    try {
      await api.knowledge.resort(docId);
      toast.success("Sorting this file. It'll be ready to review in a minute.");
      announceApprovalsChanged();
      await loadDocuments();
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Could not start sorting this file.");
    }
  }

  // ─── Viewer & Downloader ───────────────────────────────────────────────────

  async function openDocument(docId: string) {
    setViewerLoading(true);
    setViewerSearch("");
    setFactsEditing(false);
    try {
      const content = await api.knowledge.documentContent(docId);
      setViewingDoc(content);
    } catch {
      toast.error("Could not load document text.");
    } finally {
      setViewerLoading(false);
    }
  }

  async function downloadDocument(docId: string) {
    setDownloading(true);
    try {
      const { url } = await api.knowledge.documentDownloadUrl(docId);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      toast.error("The original file is not available for this document.");
    } finally {
      setDownloading(false);
    }
  }

  function renderSortAction(doc: KnowledgeDoc) {
    if (!canManageKnowledge) return null;
    const status = docStatus(doc);
    if (status === "review") {
      return (
        <button
          onClick={() => setReviewingDocId(doc.id)}
          className="flex items-center gap-1 px-2.5 py-1 mr-1 rounded-lg bg-primary text-white font-label text-[11px] font-bold hover:bg-primary/90 transition-colors shadow-xs"
        >
          <ClipboardCheck size={12} /> Review
        </button>
      );
    }
    if (status === "unsorted" || status === "sort_failed" || status === "failed") {
      const label = status === "unsorted" ? "Sort this file" : "Sort again";
      return (
        <button
          onClick={() => resortDocument(doc.id)}
          title={label}
          className="flex items-center gap-1 px-2 py-1 mr-1 rounded-lg border border-surface-mid bg-white text-on-surface font-label text-[11px] font-semibold hover:bg-surface-low transition-colors"
        >
          <RefreshCw size={12} /> {label}
        </button>
      );
    }
    return null;
  }

  // Stacked card row for the Documents table on phone widths (below md), where a
  // 6-column table forces horizontal scroll to reach Status/Actions. Reuses the
  // same status badge, scope pill, and action handlers as the table/grid rows --
  // no duplicated logic, just different markup for narrow screens.
  function renderDocRow(doc: KnowledgeDoc) {
    const meta = getFileTypeMeta(doc.file_type, doc.name);
    const campaignTag = doc.campaign_tag_id ? tagMap.get(doc.campaign_tag_id) : null;

    return (
      <div key={doc.id} className="p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "w-9 h-9 rounded-xl flex items-center justify-center shrink-0",
              meta.iconBg,
              meta.iconColor
            )}
          >
            {meta.category === "spreadsheet" ? (
              <FileSpreadsheet size={18} />
            ) : meta.category === "image" ? (
              <ImageIcon size={18} />
            ) : meta.category === "text" ? (
              <FileCode size={18} />
            ) : (
              <FileText size={18} />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-on-surface text-sm truncate" title={doc.name}>
              {doc.name}
            </p>
            <p className="font-mono text-[11px] text-on-surface-muted mt-0.5">
              {formatBytes(doc.size_bytes)} · {formatDate(doc.created_at)}
            </p>
            {(doc.status === "failed" || doc.sort_state === "failed") && (
              <p className="text-[11px] text-red-600 mt-1" title={doc.error_message || undefined}>
                {doc.error_message || "Extraction error — delete & re-upload"}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <DocStatusBadge doc={doc} />
          <span
            className={cn(
              "inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider border",
              meta.badgeBg,
              meta.badgeText,
              meta.badgeBorder
            )}
          >
            {meta.label}
          </span>
          {campaignTag ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-primary-50 text-primary-700 text-[11px] font-semibold border border-primary-100">
              <Tag size={11} /> {campaignTag.name}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface-low text-on-surface-muted text-[11px] font-medium border border-surface-mid">
              🌐 Shared
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 pt-1">
          {renderSortAction(doc)}
          <button
            onClick={() => openDocument(doc.id)}
            title="What Anril looks up from this file"
            className="p-2 text-on-surface-muted hover:text-primary hover:bg-primary/5 rounded-lg transition-colors"
          >
            <Eye size={16} />
          </button>
          <button
            onClick={() => downloadDocument(doc.id)}
            title="Download original file"
            className="p-2 text-on-surface-muted hover:text-primary hover:bg-primary/5 rounded-lg transition-colors"
          >
            <Download size={16} />
          </button>
          {canManageKnowledge && (
            <button
              onClick={() => setDeletingDoc(doc)}
              title="Delete document"
              className="p-2 text-on-surface-muted hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              <Trash2 size={16} />
            </button>
          )}
        </div>
      </div>
    );
  }

  async function saveFacts() {
    if (!viewingDoc) return;
    setFactsSaving(true);
    try {
      const res = await api.knowledge.updateFacts(viewingDoc.id, factsDraft);
      setViewingDoc({ ...viewingDoc, full_text: res.full_text });
      setFactsEditing(false);
      toast.success("Saved. Anril will look up the updated facts.");
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Could not save your changes.");
    } finally {
      setFactsSaving(false);
    }
  }

  function copyExtractedText() {
    if (!viewingDoc?.full_text) return;
    navigator.clipboard.writeText(viewingDoc.full_text);
    setCopiedText(true);
    toast.success("Document text copied to clipboard.");
    setTimeout(() => setCopiedText(false), 2000);
  }

  // ─── AI Tuning Handlers ───────────────────────────────────────────────────

  async function saveRubric() {
    setRubricSaving(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ updates: { scoring_rubric: scoringRubric } }),
      });
      if (!res.ok) throw new Error("Save failed");
      setSavedRubric(scoringRubric);
      toast.success("Scoring rubric saved.");
    } catch {
      toast.error("Failed to save rubric. Please try again.");
    } finally {
      setRubricSaving(false);
    }
  }

  async function toggleRubricAutoUpdate(next: boolean) {
    setRubricToggleSaving(true);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/settings/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ updates: { rubric_auto_update: next ? "true" : "false" } }),
      });
      if (!res.ok) throw new Error("Save failed");
      setRubricAutoUpdate(next);
      toast.success(
        next
          ? "Rubric will update automatically when you save your description."
          : "Rubric will no longer change when you save your description."
      );
    } catch {
      toast.error("Could not change setting. Please try again.");
    } finally {
      setRubricToggleSaving(false);
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    // No `space-y-*` on this wrapper. Both tab branches below carry their own, so it
    // spaced nothing -- but Tailwind's `space-y-6 > :not([hidden]) ~ :not([hidden])`
    // applied `margin-top: 24px` to EVERY later child, and the modals below are later
    // children. A `position: fixed; inset: 0` overlay with a 24px top margin cannot
    // reach the top of the viewport, so every modal left a 24px undimmed strip across
    // the top of the screen with the app header showing through it. Verified in Chrome:
    // the overlay's rect was y=24 h=776 in an 800px viewport.
    <div className="max-w-7xl mx-auto">
      <ConflictsLink className="mb-6" />

      {tab === "documents" ? (
        <div className="space-y-6">
          {/* ── Top Overview Stats ────────────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-surface rounded-2xl p-4 border border-surface-mid border-t-4 border-t-sky-400 shadow-sm flex items-center justify-between">
              <div>
                <p className="font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">
                  Total Documents
                </p>
                <p className="font-display text-2xl font-black text-on-surface mt-1">
                  {loading ? "—" : stats.total.toLocaleString()}
                </p>
                <p className="font-body text-[11px] text-on-surface-muted mt-0.5">
                  Across all formats
                </p>
              </div>
              <div className="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center text-primary shrink-0">
                <BookOpen size={20} />
              </div>
            </div>

            <div className="bg-surface rounded-2xl p-4 border border-surface-mid border-t-4 border-t-emerald-400 shadow-sm flex items-center justify-between">
              <div>
                <p className="font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">
                  Active & Indexed
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <p className="font-display text-2xl font-black text-emerald-700">
                    {loading ? "—" : stats.indexed.toLocaleString()}
                  </p>
                  {!loading && stats.processing > 0 && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-bold">
                      <Loader2 size={10} className="animate-spin" />
                      {stats.processing} sorting
                    </span>
                  )}
                </div>
                <p
                  className={cn(
                    "font-body text-[11px] font-semibold mt-0.5",
                    !loading && stats.notSearchable > 0 ? "text-amber-700" : "text-emerald-700"
                  )}
                >
                  {loading
                    ? "—"
                    : stats.notSearchable > 0
                    ? `${stats.notSearchable} not searchable`
                    : "Ready for AI RAG retrieval"}
                </p>
              </div>
              <div className="w-11 h-11 rounded-xl bg-emerald-50 flex items-center justify-center text-emerald-600 shrink-0">
                <Sparkles size={20} />
              </div>
            </div>

            <div className="bg-surface rounded-2xl p-4 border border-surface-mid border-t-4 border-t-amber-400 shadow-sm flex items-center justify-between">
              <div>
                <p className="font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">
                  Storage Footprint
                </p>
                <p className="font-display text-2xl font-black text-on-surface mt-1">
                  {loading ? "—" : formatBytes(stats.totalBytes)}
                </p>
                <p className="font-body text-[11px] text-on-surface-muted mt-0.5">
                  Indexed vector data
                </p>
              </div>
              <div className="w-11 h-11 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                <HardDrive size={20} />
              </div>
            </div>

            <div className="bg-surface rounded-2xl p-4 border border-surface-mid border-t-4 border-t-purple-400 shadow-sm flex items-center justify-between">
              <div>
                <p className="font-label text-xs font-bold text-on-surface-muted uppercase tracking-wider">
                  Campaign Scopes
                </p>
                <p className="font-display text-2xl font-black text-on-surface mt-1">
                  {loading ? "—" : stats.scopedCount > 0 ? `${stats.scopedCount} Scoped` : "All Shared"}
                </p>
                <p className="font-body text-[11px] text-on-surface-muted mt-0.5">
                  {loading ? "—" : campaignTags.length} campaigns available
                </p>
              </div>
              <div className="w-11 h-11 rounded-xl bg-primary-50 flex items-center justify-center text-primary-600 shrink-0">
                <Tag size={20} />
              </div>
            </div>
          </div>

          {gapQuestion && (
            <KnowledgeGapAnswerForm
              key={`${gapQuestion}:${uploadedDocumentId ?? ""}`}
              question={gapQuestion}
              uploadedDocumentId={uploadedDocumentId}
              canManage={canManageKnowledge}
              onUploaded={async () => {
                announceApprovalsChanged();
                await loadDocuments();
              }}
            />
          )}

          {/* ── Modern Upload Zone Card ───────────────────────────────────── */}
          <div className="bg-surface rounded-2xl border border-surface-mid shadow-sm overflow-hidden">
            {/* Header / Scope selector bar */}
            <div className="p-4 sm:p-5 border-b border-surface-mid/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-surface-low/50">
              <div>
                <h2 className="font-display font-bold text-base text-on-surface flex items-center gap-2">
                  <Upload size={18} className="text-primary" />
                  Add Knowledge Document
                </h2>
                <p className="font-body text-xs text-on-surface-muted mt-0.5">
                  Upload anything you have — rulebooks, price lists, FAQs. Anril sorts each file into rules for your Description and facts to look up, and you review it before anything changes.
                </p>
              </div>

              <div className="flex flex-col sm:items-end gap-2 shrink-0">
              {canManageKnowledge && documents.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="font-label text-xs font-semibold text-on-surface-muted">
                    Replaces:
                  </span>
                  <select
                    value={replaceTarget}
                    onChange={(e) => setReplaceTarget(e.target.value)}
                    disabled={uploading}
                    title="Does this upload replace an existing file? The old file is removed only when you apply the new one."
                    className="max-w-[14rem] px-3 py-1.5 rounded-xl border border-surface-mid bg-white font-body text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xs"
                  >
                    <option value="">Nothing — it&apos;s a new file</option>
                    {documents
                      .filter((d) => docStatus(d) !== "review" && docStatus(d) !== "sorting")
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                  </select>
                </div>
              )}
              {campaignTags.length > 0 && (
                <div className="flex items-center gap-2 shrink-0">
                  <span className="font-label text-xs font-semibold text-on-surface-muted">
                    Campaign Scope:
                  </span>
                  <select
                    value={selectedCampaignTag}
                    onChange={(e) => setSelectedCampaignTag(e.target.value)}
                    disabled={uploading}
                    className="px-3 py-1.5 rounded-xl border border-surface-mid bg-white font-body text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xs"
                  >
                    <option value="">🌐 All campaigns (shared)</option>
                    {campaignTags.map((t) => (
                      <option key={t.id} value={t.id}>
                        🎯 {t.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              </div>
            </div>

            {/* ── Business Kit readiness: one line, nudges only (spec 2026-09-24) ── */}
            {setupLoaded && (
              <ReadinessLine
                refreshKey={readinessKey}
                isOwner={isOwner}
                canManage={canManageKnowledge}
                onOpenDescription={goToDescription}
                onAddText={(file) => processUpload(file, null)}
              />
            )}

            {/* Drag & Drop Area (plus a rubric hint while one is missing) */}
            <div className="p-4 sm:p-6">
              {showStartHint && (
                <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50/40 p-4 sm:p-5 flex flex-col sm:flex-row gap-4">
                  <div className="w-10 h-10 shrink-0 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center">
                    <Lightbulb size={20} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-display text-sm font-bold text-on-surface">
                      No lead scoring rubric yet
                    </p>
                    <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed max-w-2xl">
                      The rubric tells Anril how to classify leads as Hot, Warm, or Cold. It&rsquo;s written for you from
                      your Description the first time you save one, or you can write your own. It
                      doesn&rsquo;t hold up uploads &mdash; nothing here does.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={goToDescription}
                    className="self-start shrink-0 flex items-center gap-2 px-4 py-2 bg-white border border-surface-mid text-primary rounded-xl font-label text-xs font-semibold hover:bg-primary/5 transition-colors shadow-xs"
                  >
                    Write a rubric <ArrowRight size={14} />
                  </button>
                </div>
              )}

              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={cn(
                  "relative rounded-2xl border-2 border-dashed p-8 transition-colors flex flex-col items-center justify-center text-center group",
                  isDragging
                    ? "border-primary bg-primary/[0.08] shadow-inner"
                    : "border-primary/30 bg-primary/[0.02] hover:border-primary/60 hover:bg-primary/[0.04]",
                  uploading && "pointer-events-none opacity-60"
                )}
              >
                <div
                  className={cn(
                    "w-14 h-14 rounded-2xl flex items-center justify-center transition-colors shadow-xs mb-3",
                    isDragging || uploading
                      ? "bg-primary text-white"
                      : "bg-primary/10 text-primary group-hover:bg-primary/20"
                  )}
                >
                  {uploading ? (
                    <Loader2 size={26} className="animate-spin" />
                  ) : (
                    <Upload size={26} />
                  )}
                </div>

                <p className="font-display text-base font-bold text-on-surface">
                  {uploading
                    ? "Uploading…"
                    : isDragging
                    ? "Drop your file here to upload"
                    : "Drop your file here or browse from computer"}
                </p>

                <p className="font-body text-xs text-on-surface-muted mt-1 max-w-md">
                  Supports PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, and Images up to 25 MB.
                </p>

                {/* Formats badge row */}
                <div className="flex flex-wrap items-center justify-center gap-1.5 mt-3">
                  {["PDF", "DOCX", "EXCEL", "CSV", "PPTX", "TXT", "MD", "IMAGES"].map((fmt) => (
                    <span
                      key={fmt}
                      className="px-2 py-0.5 rounded-md bg-white border border-surface-mid/80 text-[10px] font-mono font-bold text-on-surface-muted"
                    >
                      {fmt}
                    </span>
                  ))}
                </div>

                {/* Scope pill reminder */}
                {selectedCampaignTag && (
                  <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary-50 text-primary-700 text-xs font-semibold border border-primary-100">
                    <Tag size={12} />
                    Will be scoped exclusively to &quot;{tagMap.get(selectedCampaignTag)?.name}&quot;
                  </div>
                )}

                {/* Choose file button */}
                <div className="mt-5">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading || !canUpload}
                    className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-xs"
                  >
                    <Plus size={16} />
                    Choose File to Upload
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.txt,.md,.markdown,image/*"
                    onChange={handleFileSelect}
                    className="hidden"
                  />
                </div>

                {canUpload && <KitStarter compact={documents.length > 0} />}
              </div>

              {uploadError && (
                <div className="mt-3 flex items-center gap-2 p-3 bg-red-50 text-red-700 rounded-xl text-xs font-semibold border border-red-200">
                  <AlertCircle size={16} className="shrink-0" />
                  <span>{uploadError}</span>
                  <button
                    onClick={() => setUploadError(null)}
                    className="ml-auto text-red-500 hover:text-red-700 font-bold"
                  >
                    Dismiss
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* ── Filter & Search Toolbar ───────────────────────────────────── */}
          {/* Hidden while there is nothing to filter (2026-09-20). On an empty
              knowledge base this let you set a filter over a list that could not
              contain anything, leaving an "Active Filters: Type: Word ✕ Reset all"
              chip sitting above "No documents in your knowledge base yet".
              Gated on `documents`, not `filteredDocs` — gating on the filtered list
              would make the toolbar delete itself the moment a filter matched
              nothing, taking away the only control that could undo it. */}
          {documents.length > 0 && (
          <div className="bg-surface rounded-2xl p-4 border border-surface-mid shadow-sm space-y-3">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              {/* Search Bar */}
              <div className="relative flex-1 min-w-0 max-w-md">
                <Search
                  size={16}
                  className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-muted"
                />
                <input
                  type="text"
                  placeholder="Search documents by name or campaign tag..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-9 pr-8 py-2 rounded-xl bg-surface-low border border-surface-mid font-body text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors"
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-on-surface-muted hover:text-on-surface p-0.5"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>

              {/* Filters & View Switcher */}
              <div className="flex flex-wrap items-center gap-2">
                {/* Format Filter */}
                <select
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  className="px-3 py-2 rounded-xl border border-surface-mid bg-white font-body text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xs"
                >
                  <option value="all">All File Types</option>
                  <option value="pdf">PDF Documents</option>
                  <option value="word">Word (.docx, .doc)</option>
                  <option value="spreadsheet">Excel & CSV</option>
                  <option value="presentation">PowerPoint (.pptx)</option>
                  <option value="text">Text & Markdown</option>
                  <option value="image">Images</option>
                </select>

                {/* Status Filter */}
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="px-3 py-2 rounded-xl border border-surface-mid bg-white font-body text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xs"
                >
                  <option value="all">All Statuses</option>
                  <option value="live">Live</option>
                  <option value="unsorted">Not sorted</option>
                  <option value="review">Review ready ({stats.review})</option>
                  <option value="sorting">Sorting ({stats.processing})</option>
                  <option value="failed">Failed ({stats.failed})</option>
                </select>

                {/* Campaign Scope Filter */}
                {campaignTags.length > 0 && (
                  <select
                    value={campaignFilter}
                    onChange={(e) => setCampaignFilter(e.target.value)}
                    className="px-3 py-2 rounded-xl border border-surface-mid bg-white font-body text-xs text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20 shadow-xs"
                  >
                    <option value="all">All Scopes</option>
                    <option value="global">🌐 Shared / Global only</option>
                    {campaignTags.map((t) => (
                      <option key={t.id} value={t.id}>
                        🎯 {t.name}
                      </option>
                    ))}
                  </select>
                )}

                {/* View Mode Switcher */}
                <div className="flex items-center rounded-xl bg-surface-low border border-surface-mid p-0.5">
                  <button
                    onClick={() => setViewMode("table")}
                    title="List View"
                    className={cn(
                      "p-1.5 rounded-lg transition-colors",
                      viewMode === "table"
                        ? "bg-white text-primary shadow-xs"
                        : "text-on-surface-muted hover:text-on-surface"
                    )}
                  >
                    <List size={16} />
                  </button>
                  <button
                    onClick={() => setViewMode("grid")}
                    title="Grid View"
                    className={cn(
                      "p-1.5 rounded-lg transition-colors",
                      viewMode === "grid"
                        ? "bg-white text-primary shadow-xs"
                        : "text-on-surface-muted hover:text-on-surface"
                    )}
                  >
                    <LayoutGrid size={16} />
                  </button>
                </div>
              </div>
            </div>

            {/* Active filters pill list */}
            {(search || categoryFilter !== "all" || statusFilter !== "all" || campaignFilter !== "all") && (
              <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-surface-mid/50 text-xs">
                <span className="font-label text-on-surface-muted font-bold text-[10px] uppercase">
                  Active Filters:
                </span>
                {search && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-mid text-on-surface font-medium text-xs">
                    Search: &quot;{search}&quot;
                    <button onClick={() => setSearch("")} className="hover:text-red-500">
                      <X size={12} />
                    </button>
                  </span>
                )}
                {categoryFilter !== "all" && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-mid text-on-surface font-medium text-xs capitalize">
                    Type: {categoryFilter}
                    <button onClick={() => setCategoryFilter("all")} className="hover:text-red-500">
                      <X size={12} />
                    </button>
                  </span>
                )}
                {statusFilter !== "all" && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-mid text-on-surface font-medium text-xs capitalize">
                    Status: {statusFilter}
                    <button onClick={() => setStatusFilter("all")} className="hover:text-red-500">
                      <X size={12} />
                    </button>
                  </span>
                )}
                {campaignFilter !== "all" && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-mid text-on-surface font-medium text-xs">
                    Scope: {campaignFilter === "global" ? "Global" : tagMap.get(campaignFilter)?.name}
                    <button onClick={() => setCampaignFilter("all")} className="hover:text-red-500">
                      <X size={12} />
                    </button>
                  </span>
                )}
                <button
                  onClick={() => {
                    setSearch("");
                    setCategoryFilter("all");
                    setStatusFilter("all");
                    setCampaignFilter("all");
                  }}
                  className="font-label text-xs font-bold text-primary hover:underline ml-1"
                >
                  Reset all
                </button>
              </div>
            )}
          </div>
          )}

          {/* ── Document List / Grid Section ──────────────────────────────── */}
          <div className="bg-surface rounded-2xl border border-surface-mid shadow-sm overflow-hidden">
            {loading ? (
              <AiraLoader inline className="min-h-[200px]" />
            ) : filteredDocs.length === 0 ? (
              <div className="py-16 px-4 text-center">
                <div className="w-14 h-14 rounded-2xl bg-surface-low border border-surface-mid flex items-center justify-center mx-auto mb-3 text-on-surface-muted">
                  <FileText size={26} />
                </div>
                {documents.length === 0 ? (
                  <>
                    <h3 className="font-display text-base font-bold text-on-surface">
                      No documents in your knowledge base yet
                    </h3>
                    {/* No upload button here on purpose (2026-09-20). The drop zone
                        card directly above is the ONE place to upload; a second CTA
                        on the same empty screen read as two different upload routes.
                        The copy points up at it instead. */}
                    <p className="font-body text-xs text-on-surface-muted mt-1 max-w-sm mx-auto">
                      Upload rulebooks, FAQs, price lists or brochures using the box above. Anril sorts each one and shows you the result before anything changes.
                    </p>
                  </>
                ) : (
                  <>
                    <h3 className="font-display text-base font-bold text-on-surface">
                      No documents match your filters
                    </h3>
                    <p className="font-body text-xs text-on-surface-muted mt-1">
                      Try clearing search terms or selecting &quot;All File Types&quot;.
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setSearch("");
                        setCategoryFilter("all");
                        setStatusFilter("all");
                        setCampaignFilter("all");
                      }}
                      className="mt-4 px-4 py-2 bg-surface-low hover:bg-surface-mid rounded-xl font-label text-xs font-bold text-on-surface border border-surface-mid transition-colors"
                    >
                      Clear Filters
                    </button>
                  </>
                )}
              </div>
            ) : viewMode === "grid" ? (
              /* ── Grid Cards View ── */
              <div className="p-4 sm:p-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredDocs.map((doc) => {
                  const meta = getFileTypeMeta(doc.file_type, doc.name);
                  const campaignTag = doc.campaign_tag_id ? tagMap.get(doc.campaign_tag_id) : null;

                  return (
                    <div
                      key={doc.id}
                      className="bg-white rounded-2xl border border-surface-mid p-5 shadow-xs hover:shadow-card hover:border-primary/30 transition-all flex flex-col justify-between group"
                    >
                      <div>
                        {/* Top card bar: icon + type badge + status */}
                        <div className="flex items-start justify-between gap-2 mb-3">
                          <div className="flex items-center gap-2">
                            <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shrink-0", meta.iconBg, meta.iconColor)}>
                              {meta.category === "spreadsheet" ? (
                                <FileSpreadsheet size={20} />
                              ) : meta.category === "image" ? (
                                <ImageIcon size={20} />
                              ) : meta.category === "text" ? (
                                <FileCode size={20} />
                              ) : (
                                <FileText size={20} />
                              )}
                            </div>
                            <div>
                              <span
                                className={cn(
                                  "inline-block px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide border",
                                  meta.badgeBg,
                                  meta.badgeText,
                                  meta.badgeBorder
                                )}
                              >
                                {meta.label}
                              </span>
                              <p className="font-mono text-[10px] text-on-surface-muted mt-0.5">
                                {formatBytes(doc.size_bytes)}
                              </p>
                            </div>
                          </div>

                          {/* Status Badge */}
                          <DocStatusBadge doc={doc} className="shrink-0" />
                        </div>

                        {/* Title */}
                        <h4
                          className="font-display font-bold text-sm text-on-surface line-clamp-2 leading-snug group-hover:text-primary transition-colors"
                          title={doc.name}
                        >
                          {doc.name}
                        </h4>

                        {/* Campaign Scope Pill */}
                        <div className="mt-3">
                          {campaignTag ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-primary-50 text-primary-700 text-[11px] font-semibold border border-primary-100">
                              <Tag size={11} /> {campaignTag.name}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-surface-low text-on-surface-muted text-[11px] font-medium border border-surface-mid">
                              🌐 All campaigns (shared)
                            </span>
                          )}
                        </div>

                        {/* Error message if failed */}
                        {(doc.status === "failed" || doc.sort_state === "failed") && (
                          <p className="text-xs text-red-600 mt-2 bg-red-50 p-2 rounded-lg border border-red-100">
                            {doc.error_message || "Extraction failed. Try re-uploading file."}
                          </p>
                        )}
                      </div>

                      {/* Footer: Date & Actions */}
                      <div className="pt-4 mt-4 border-t border-surface-mid/60 flex items-center justify-between">
                        <span className="font-body text-[11px] text-on-surface-muted">
                          {formatDate(doc.created_at)}
                        </span>

                        <div className="flex items-center gap-1">
                          {renderSortAction(doc)}
                          <button
                            onClick={() => openDocument(doc.id)}
                            title="What Anril looks up from this file"
                            className="p-1.5 text-on-surface-muted hover:text-primary hover:bg-primary/5 rounded-lg transition-colors"
                          >
                            <Eye size={16} />
                          </button>
                          <button
                            onClick={() => downloadDocument(doc.id)}
                            title="Download original file"
                            className="p-1.5 text-on-surface-muted hover:text-primary hover:bg-primary/5 rounded-lg transition-colors"
                          >
                            <Download size={16} />
                          </button>
                          {canManageKnowledge && (
                            <button
                              onClick={() => setDeletingDoc(doc)}
                              title="Delete document"
                              className="p-1.5 text-on-surface-muted hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                            >
                              <Trash2 size={16} />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              /* ── Modern Table View (md and up) + Stacked Rows (phone) ── */
              <>
                {/* Below md, a 6-column table forces sideways scrolling to reach
                    Status/Actions, so phones get stacked cards instead. */}
                <div className="md:hidden divide-y divide-surface-mid/60">
                  {filteredDocs.map((doc) => renderDocRow(doc))}
                </div>

                <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-left font-body text-sm">
                  <thead>
                    <tr className="bg-surface-low/80 border-b border-surface-mid text-[11px] font-label font-bold text-on-surface-muted uppercase tracking-wider">
                      <th className="px-5 py-3.5">Document</th>
                      <th className="px-4 py-3.5">Format</th>
                      <th className="px-4 py-3.5">Scope</th>
                      <th className="px-4 py-3.5">Status</th>
                      <th className="px-4 py-3.5">Uploaded</th>
                      <th className="px-5 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-mid/60">
                    {filteredDocs.map((doc) => {
                      const meta = getFileTypeMeta(doc.file_type, doc.name);
                      const campaignTag = doc.campaign_tag_id ? tagMap.get(doc.campaign_tag_id) : null;

                      return (
                        <tr
                          key={doc.id}
                          className="hover:bg-surface-low/60 transition-colors group"
                        >
                          {/* Document Name & Size */}
                          <td className="px-5 py-3.5 max-w-sm">
                            <div className="flex items-center gap-3">
                              <div
                                className={cn(
                                  "w-9 h-9 rounded-xl flex items-center justify-center shrink-0",
                                  meta.iconBg,
                                  meta.iconColor
                                )}
                              >
                                {meta.category === "spreadsheet" ? (
                                  <FileSpreadsheet size={18} />
                                ) : meta.category === "image" ? (
                                  <ImageIcon size={18} />
                                ) : meta.category === "text" ? (
                                  <FileCode size={18} />
                                ) : (
                                  <FileText size={18} />
                                )}
                              </div>
                              <div className="min-w-0">
                                <p
                                  className="font-semibold text-on-surface text-sm truncate group-hover:text-primary transition-colors"
                                  title={doc.name}
                                >
                                  {doc.name}
                                </p>
                                <p className="font-mono text-[11px] text-on-surface-muted mt-0.5">
                                  {formatBytes(doc.size_bytes)}
                                </p>
                                {(doc.status === "failed" || doc.sort_state === "failed") && (
                                  <p className="text-[11px] text-red-600 truncate mt-0.5 max-w-xs" title={doc.error_message || undefined}>
                                    {doc.error_message || "Extraction error — delete & re-upload"}
                                  </p>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* Clean Format Badge */}
                          <td className="px-4 py-3.5 whitespace-nowrap">
                            <span
                              className={cn(
                                "inline-flex items-center px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider border",
                                meta.badgeBg,
                                meta.badgeText,
                                meta.badgeBorder
                              )}
                            >
                              {meta.label}
                            </span>
                          </td>

                          {/* Campaign Scope */}
                          <td className="px-4 py-3.5 whitespace-nowrap">
                            {campaignTag ? (
                              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-primary-50 text-primary-700 text-xs font-semibold border border-primary-100">
                                <Tag size={11} /> {campaignTag.name}
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface-low text-on-surface-muted text-xs font-medium border border-surface-mid">
                                🌐 Shared
                              </span>
                            )}
                          </td>

                          {/* Status */}
                          <td className="px-4 py-3.5 whitespace-nowrap">
                            <DocStatusBadge doc={doc} />
                          </td>

                          {/* Created Date */}
                          <td className="px-4 py-3.5 whitespace-nowrap text-on-surface-muted text-xs">
                            {formatDate(doc.created_at)}
                          </td>

                          {/* Actions */}
                          <td className="px-5 py-3.5 text-right whitespace-nowrap">
                            <div className="flex items-center justify-end gap-1">
                              {renderSortAction(doc)}
                              <button
                                onClick={() => openDocument(doc.id)}
                                title="What Anril looks up from this file"
                                className="p-2 text-on-surface-muted hover:text-primary hover:bg-primary/5 rounded-lg transition-colors"
                              >
                                <Eye size={16} />
                              </button>
                              <button
                                onClick={() => downloadDocument(doc.id)}
                                title="Download original file"
                                className="p-2 text-on-surface-muted hover:text-primary hover:bg-primary/5 rounded-lg transition-colors"
                              >
                                <Download size={16} />
                              </button>
                              {canManageKnowledge && (
                                <button
                                  onClick={() => setDeletingDoc(doc)}
                                  title="Delete document"
                                  className="p-2 text-on-surface-muted hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                >
                                  <Trash2 size={16} />
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
              </>
            )}
          </div>

        </div>
      ) : (
        /* ── Description Tab ─────────────────────────────────────────────── */
        <div className="space-y-6">
          {/* Business Profile Editor */}
          <ProfileSectionsEditor
            canEdit={isOwner}
            onOpenHistory={() => setHistoryTarget({ kind: "description", title: "Description" })}
            onSaved={() => {
              // Update savedDescription to reflect the new word count from the profile
              // This keeps the Documents tab status row in sync.
              // We use loadDescription() to refetch the full text state.
              loadDescription();
            }}
          />

          {/* Scoring Rubric */}
          <div className="bg-surface rounded-2xl p-6 md:p-8 border border-surface-mid shadow-sm space-y-4">
            <div>
              <h2 className="font-display text-lg font-bold text-primary">
                Lead Scoring Rubric (Hot / Warm / Cold)
              </h2>
              <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed">
                The criteria used by Anril to classify leads into Hot, Warm, or Cold categories based on conversation transcripts. You can edit this rubric manually or toggle auto-update to sync with your product description.
              </p>
            </div>

            <div className="flex items-start justify-between gap-4 rounded-xl border border-surface-mid bg-surface-low p-4">
              <div>
                <p className="font-label text-sm font-semibold text-on-surface">
                  Auto-generate rubric from product description
                </p>
                <p className="font-body text-xs text-on-surface-muted mt-0.5 leading-relaxed">
                  {rubricAutoUpdate
                    ? "Active: saving your description will automatically update this rubric based on your updated products/services."
                    : "Disabled: manual rubric changes below will be preserved and won't be modified when editing your product description."}
                </p>
              </div>

              <div className="mt-0.5">
                <SwitchPill
                  on={rubricAutoUpdate}
                  onChange={toggleRubricAutoUpdate}
                  loading={rubricToggleSaving}
                  disabled={!canManageKnowledge || !setupLoaded || rubricLoadFailed}
                  aria-label="Auto-generate rubric from product description"
                />
              </div>
            </div>

            {!setupLoaded ? (
              <AiraLoader inline className="min-h-[200px]" />
            ) : rubricLoadFailed ? (
              <SectionLoadGate state="error" onRetry={() => { setSetupLoaded(false); void loadAiTuneSettings().finally(() => setSetupLoaded(true)); }}>{null}</SectionLoadGate>
            ) : (
              <>
                <AutoGrowTextarea
                  value={scoringRubric}
                  onChange={(e) => setScoringRubric(e.target.value)}
                  minRows={5}
                  spellCheck={false}
                  placeholder={
                    "- Hot: Asked for pricing, booking slot, or callback; ready to proceed\n" +
                    "- Warm: Clear interest, detailed questions, comparing options, providing info\n" +
                    "- Cold: General inquiry, first contact, vague replies, no follow-up"
                  }
                  className="w-full px-4 py-3.5 rounded-xl bg-surface-low border border-surface-mid font-mono text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-colors"
                />

                <div className="flex justify-end pt-2">
                  <button
                    onClick={saveRubric}
                    disabled={rubricSaving || scoringRubric === savedRubric || !canManageKnowledge}
                    className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-xs"
                  >
                    <Save size={14} /> {rubricSaving ? "Saving…" : "Save Rubric"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Extracted Document Viewer Loading Overlay ───────────────────────── */}
      {viewerLoading && !viewingDoc && (
        <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-surface rounded-2xl p-5 shadow-2xl border border-surface-mid flex items-center gap-3">
            <Loader2 size={24} className="animate-spin text-primary" />
            <span className="font-body text-sm font-semibold text-on-surface">Loading document content…</span>
          </div>
        </div>
      )}

      {/* ── Extracted Document Viewer Modal ─────────────────────────────────── */}
      {viewingDoc && (
        <div
          className="fixed inset-0 z-dialog flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
          onClick={() => setViewingDoc(null)}
        >
          <div
            className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-surface shadow-2xl border border-surface-mid"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-start justify-between gap-4 border-b border-surface-mid px-6 py-4 bg-surface-low/50">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider border",
                      getFileTypeMeta(viewingDoc.file_type, viewingDoc.name).badgeBg,
                      getFileTypeMeta(viewingDoc.file_type, viewingDoc.name).badgeText,
                      getFileTypeMeta(viewingDoc.file_type, viewingDoc.name).badgeBorder
                    )}
                  >
                    {getFileTypeMeta(viewingDoc.file_type, viewingDoc.name).label}
                  </span>
                  <h3 className="truncate font-display text-base font-bold text-on-surface">
                    {viewingDoc.name}
                  </h3>
                </div>
                <p className="mt-1 font-label text-[11px] font-bold uppercase tracking-wider text-primary">
                  {viewingDoc.sorted ? "What Anril looks up from this file" : "Not sorted yet — Anril reads all of this file"}
                </p>
                <p className="mt-0.5 font-body text-xs text-on-surface-muted">
                  {formatBytes(viewingDoc.size_bytes)} ·{" "}
                  {viewingDoc.full_text?.length.toLocaleString() || 0} characters ·{" "}
                  Uploaded {formatDate(viewingDoc.created_at)}
                </p>
              </div>

              <button
                onClick={() => setViewingDoc(null)}
                className="rounded-lg p-1.5 text-on-surface-muted hover:bg-surface-mid hover:text-on-surface transition-colors"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>

            {/* In-Modal Search Bar */}
            <div className="px-6 py-2.5 border-b border-surface-mid/60 bg-white flex items-center gap-2">
              <Search size={14} className="text-on-surface-muted" />
              <input
                type="text"
                placeholder="Find in document text..."
                value={viewerSearch}
                onChange={(e) => setViewerSearch(e.target.value)}
                className="flex-1 min-w-0 bg-transparent text-xs font-body focus:outline-none text-on-surface"
              />
              {viewerSearch && (
                <button
                  onClick={() => setViewerSearch("")}
                  className="text-on-surface-muted hover:text-on-surface p-0.5"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Content Body */}
            <div className="flex-1 overflow-y-auto px-6 py-4 bg-surface-low/30">
              {!viewingDoc.sorted && (
                <div className="mb-3 flex flex-col sm:flex-row sm:items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="flex-1 font-body text-xs leading-relaxed text-amber-900">
                    This file was uploaded before auto-sort, so Anril treats all of it as facts, rules included.
                    Sort it to move the rules into your Description and keep only the facts here.
                  </p>
                  {canManageKnowledge && viewingDoc.sort_state !== "sorting" && (
                    <button
                      onClick={() => {
                        const id = viewingDoc.id;
                        setViewingDoc(null);
                        resortDocument(id);
                      }}
                      className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-600 text-white font-label text-xs font-semibold hover:bg-amber-700 transition-colors"
                    >
                      <RefreshCw size={12} /> Sort this file
                    </button>
                  )}
                </div>
              )}
              {factsEditing ? (
                <div className="space-y-2">
                  <p className="font-body text-xs text-on-surface-muted">
                    Edit or delete facts. If you upload this file again later, anything you deleted here comes back.
                  </p>
                  <textarea
                    value={factsDraft}
                    onChange={(e) => setFactsDraft(e.target.value)}
                    rows={18}
                    className="w-full rounded-xl border border-surface-mid bg-white p-4 font-mono text-xs leading-relaxed text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
              ) : viewingDoc.full_text ? (
                <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-on-surface bg-white p-4 rounded-xl border border-surface-mid/80 shadow-xs">
                  {viewerSearch
                    ? viewingDoc.full_text
                        .split(new RegExp(`(${viewerSearch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"))
                        .map((part, i) =>
                          part.toLowerCase() === viewerSearch.toLowerCase() ? (
                            <mark key={i} className="bg-amber-200 text-amber-900 rounded-xs px-0.5">
                              {part}
                            </mark>
                          ) : (
                            part
                          )
                        )
                    : viewingDoc.full_text}
                </pre>
              ) : (
                <div className="py-12 text-center font-body text-xs text-on-surface-muted">
                  <FileText size={24} className="mx-auto mb-2 opacity-40" />
                  {viewingDoc.sorted
                    ? "Nothing to look up — this file only contained rules, which went into your Description."
                    : "No text content was extracted from this file."}
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-mid px-6 py-3.5 bg-surface-low/50">
              <div className="flex flex-wrap items-center gap-2">
              {viewingDoc.sorted && canManageKnowledge && !factsEditing && (
                <button
                  onClick={() => {
                    setFactsDraft(viewingDoc.full_text || "");
                    setFactsEditing(true);
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-mid text-on-surface rounded-xl font-label text-xs font-semibold border border-surface-mid transition-colors shadow-xs"
                >
                  <Pencil size={13} /> Edit
                </button>
              )}
              {factsEditing && (
                <>
                  <button
                    onClick={saveFacts}
                    disabled={factsSaving || factsDraft === viewingDoc.full_text}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 bg-primary text-white rounded-xl font-label text-xs font-semibold hover:bg-primary/90 disabled:opacity-40 transition-colors shadow-xs"
                  >
                    {factsSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Save
                  </button>
                  <button
                    onClick={() => setFactsEditing(false)}
                    disabled={factsSaving}
                    className="px-3 py-1.5 bg-surface hover:bg-surface-mid text-on-surface rounded-xl font-label text-xs font-semibold border border-surface-mid transition-colors"
                  >
                    Cancel
                  </button>
                </>
              )}
              {viewingDoc.sorted && !factsEditing && (
                <button
                  onClick={() =>
                    setHistoryTarget({ kind: "facts", documentId: viewingDoc.id, title: viewingDoc.name })
                  }
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-mid text-on-surface rounded-xl font-label text-xs font-semibold border border-surface-mid transition-colors shadow-xs"
                >
                  <History size={13} /> History
                </button>
              )}
              {!factsEditing && (
              <button
                onClick={copyExtractedText}
                disabled={!viewingDoc.full_text}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-mid text-on-surface rounded-xl font-label text-xs font-semibold border border-surface-mid transition-colors shadow-xs"
              >
                {copiedText ? (
                  <>
                    <Check size={14} className="text-emerald-600" />
                    <span>Copied to Clipboard</span>
                  </>
                ) : (
                  <>
                    <Copy size={14} />
                    <span>Copy Text</span>
                  </>
                )}
              </button>
              )}
              </div>

              <div className="flex items-center gap-2">
                {viewingDoc.downloadable && (
                  <button
                    onClick={() => downloadDocument(viewingDoc.id)}
                    disabled={downloading}
                    className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-xl font-label text-xs font-semibold hover:bg-primary/90 disabled:opacity-40 transition-colors shadow-xs"
                  >
                    <Download size={14} />
                    {downloading ? "Preparing…" : "Download Original File"}
                  </button>
                )}
                <button
                  onClick={() => setViewingDoc(null)}
                  className="px-4 py-2 bg-surface hover:bg-surface-mid text-on-surface rounded-xl font-label text-xs font-semibold border border-surface-mid transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete (previews what leaves the Description) ─────────────────── */}
      {deletingDoc && (
        <DeleteDocumentModal
          doc={deletingDoc}
          isOwner={isOwner}
          onClose={() => setDeletingDoc(null)}
          onDeleted={(descriptionChanged) => {
            setDeletingDoc(null);
            loadDocuments();
            announceApprovalsChanged();
            if (descriptionChanged) refreshAfterDescriptionChange();
          }}
        />
      )}

      {/* ── Review a sorted file ───────────────────────────────────────────── */}
      {reviewingDocId && (
        <KnowledgeReviewModal
          documentId={reviewingDocId}
          canManage={canManageKnowledge}
          isOwner={isOwner}
          onClose={() => setReviewingDocId(null)}
          onFinished={({ descriptionChanged }) => {
            setReviewingDocId(null);
            loadDocuments();
            announceApprovalsChanged();
            if (descriptionChanged) refreshAfterDescriptionChange();
          }}
          onResorted={() => {
            setReviewingDocId(null);
            loadDocuments();
            announceApprovalsChanged();
          }}
        />
      )}

      {/* ── Version history (Description or one file's facts) ──────────────── */}
      {historyTarget && (
        <KnowledgeHistoryModal
          kind={historyTarget.kind}
          documentId={historyTarget.documentId}
          title={historyTarget.title}
          canRestore={canManageKnowledge && (historyTarget.kind === "facts" || isOwner)}
          onClose={() => setHistoryTarget(null)}
          onRestored={() => {
            const target = historyTarget;
            setHistoryTarget(null);
            if (target.kind === "description") {
              refreshAfterDescriptionChange();
            } else if (viewingDoc && viewingDoc.id === target.documentId) {
              openDocument(viewingDoc.id);
            }
          }}
        />
      )}

      {/* ── Same file name: replace or keep both ───────────────────────────── */}
      {sameNamePrompt && (
        <div
          className="fixed inset-0 z-dialog flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
          onClick={() => setSameNamePrompt(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-md rounded-2xl bg-surface p-6 shadow-2xl border border-surface-mid space-y-4 animate-in fade-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-12 h-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
              <RefreshCw size={22} />
            </div>
            <div>
              <h3 className="font-display font-bold text-lg text-on-surface">A file with this name already exists</h3>
              <p className="font-body text-xs text-on-surface-muted mt-1 leading-relaxed break-words">
                <strong className="text-on-surface">{sameNamePrompt.existing.name}</strong> is already uploaded. Is this
                a newer version of it? Replacing removes the old file once you apply the new one. Keeping both means Anril
                may quote either if they disagree.
              </p>
            </div>
            <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 pt-2 border-t border-surface-mid/60">
              <button
                type="button"
                onClick={() => {
                  const { file } = sameNamePrompt;
                  setSameNamePrompt(null);
                  processUpload(file, null);
                }}
                className="px-4 py-2 rounded-xl border border-surface-mid bg-surface font-label text-xs font-semibold text-on-surface hover:bg-surface-low transition-colors"
              >
                Keep both
              </button>
              <button
                type="button"
                onClick={() => {
                  const { file, existing } = sameNamePrompt;
                  setSameNamePrompt(null);
                  processUpload(file, existing.id);
                }}
                className="px-4 py-2 rounded-xl bg-primary text-white font-label text-xs font-semibold hover:bg-primary/90 transition-colors shadow-xs"
              >
                Replace it
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
