"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  AlertCircle,
  RefreshCw,
  Trash2,
  Send,
  Edit3,
  Lock,
  X,
  Upload,
  FileCode,
  Info,
} from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { LANGUAGES, STATUS_COLORS, detectVariables, formatNextEdit } from "../types";
import type { Button, Template } from "../types";
import WhatsAppPreview from "../components/whatsapp-preview";
import ButtonBuilder from "../components/button-builder";
import VariableInserter from "../components/variable-inserter";
import AiraId from "../components/aira-id";
import VariableMapEditor, { fieldLabel } from "../components/variable-map-editor";
import type { VariableMap } from "../components/variable-map-editor";
import FieldMessages, { BlockedReason, SampleInputs, focusFirst, useFixNotes } from "../components/field-messages";
import {
  bodyBlockers,
  buttonBlockers,
  cleanFooter,
  cleanHeader,
  footerBlockers,
  headerBlockers,
  sampleBlockers,
} from "../template-rules";
import type { Blocker } from "../template-rules";
import { useAuthRole } from "../../contexts/AuthRoleContext";

export default function TemplateDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const { role, permissions } = useAuthRole();
  const canManageTemplates = role === "owner" || permissions.includes("templates.manage");
  const templateId = params.id as string;

  const [template, setTemplate] = useState<Template | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Edit Mode state
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bodyText, setBodyText] = useState("");
  const [headerType, setHeaderType] = useState<"NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT">("NONE");
  const [headerText, setHeaderText] = useState("");
  const [headerMediaUrl, setHeaderMediaUrl] = useState("");
  // Local copy of the chosen file for the preview; Meta's handle can't be displayed.
  const [mediaPreview, setMediaPreview] = useState<{ url: string; name: string } | null>(null);
  useEffect(() => () => { if (mediaPreview) URL.revokeObjectURL(mediaPreview.url); }, [mediaPreview]);
  const [uploadingMedia, setUploadingMedia] = useState(false);
  const [footerText, setFooterText] = useState("");
  const [buttons, setButtons] = useState<Button[]>([]);
  // Meta needs sample values again on every resubmission (they aren't stored).
  const [bodySamples, setBodySamples] = useState<Record<number, string>>({});
  const [headerSample, setHeaderSample] = useState("");
  const { notes, show } = useFixNotes();
  // Unsaved Variables choices, shown in the preview bubble.
  const [mapDraft, setMapDraft] = useState<VariableMap>({});

  const headerVars = headerType === "TEXT" ? detectVariables(headerText) : [];
  const editBlockers = useMemo(() => {
    const out: Blocker[] = [];
    if (headerType === "TEXT") {
      if (!headerText.trim()) out.push({ fieldId: "template-header", message: "Add the header text", inline: false });
      out.push(...headerBlockers(headerText, "template-header"));
      if (headerVars.length === 1 && !headerSample.trim()) {
        out.push({ fieldId: "template-header-sample-1", message: "Add a sample for the header variable.", inline: true });
      }
    } else if (headerType !== "NONE" && !headerMediaUrl) {
      out.push({ fieldId: "template-header-upload", message: "Upload the header file", inline: false });
    }
    const body = bodyBlockers(bodyText, "template-body");
    out.push(...body);
    if (!body.length) out.push(...sampleBlockers(bodyText, bodySamples, "template-body-sample-"));
    out.push(...footerBlockers(footerText, "template-footer"));
    out.push(...buttonBlockers(buttons));
    return out;
  }, [headerType, headerText, headerVars.length, headerSample, headerMediaUrl, bodyText, bodySamples, footerText, buttons]);

  // Load template details
  async function loadTemplate() {
    setLoading(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/`, {
        headers: authHeaders,
      });
      if (!res.ok) throw new Error("Failed to load templates");
      const data = await res.json();
      const match = data.data.find((t: Template) => t.id === templateId);
      if (!match) throw new Error("Template not found");
      setTemplate(match);

      // Populate edit states
      setBodyText(match.body_text || "");
      setHeaderText(match.header_text || "");
      setFooterText(match.footer_text || "");
      setButtons(match.buttons || []);

      if (match.header_media_type) {
        setHeaderType(match.header_media_type.toUpperCase() as "NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT");
        setHeaderMediaUrl(match.header_media_url || "");
      } else if (match.header_text) {
        setHeaderType("TEXT");
      } else {
        setHeaderType("NONE");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (templateId) {
      loadTemplate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId]);

  // Sync template status
  async function handleSync() {
    if (!canManageTemplates) {
      setError("Read-only role: syncing template status is disabled.");
      return;
    }
    setSyncing(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/${templateId}/sync`, {
        method: "POST",
        headers: authHeaders,
      });
      if (!res.ok) throw new Error("Sync status failed");
      const updated = await res.json();
      setTemplate(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  // Delete template
  async function handleDelete() {
    if (!canManageTemplates) {
      setError("Read-only role: deleting templates is disabled.");
      return;
    }
    if (!confirm("Delete this template here and on WhatsApp? If it was approved, Meta won't let you reuse its name for 30 days.")) return;
    setDeleting(true);
    try {
      const authHeaders = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/templates/${templateId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Failed to delete template");
      }
      router.push("/dashboard/templates");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  }

  // Media upload for header
  async function handleMediaUpload(file: File) {
    if (!canManageTemplates) {
      setError("Read-only role: media upload is disabled.");
      return;
    }
    setMediaPreview({ url: URL.createObjectURL(file), name: file.name });
    setUploadingMedia(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_URL}/api/v1/templates/upload-media`, {
        method: "POST",
        headers: authHeaders,
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Couldn't upload the file. Please try again.");
      }

      const data = await res.json();
      setHeaderMediaUrl(data.header_handle);
    } catch (e) {
      setMediaPreview(null);
      setError(e instanceof Error ? e.message : "Media upload failed");
    } finally {
      setUploadingMedia(false);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      handleMediaUpload(file);
    }
  }

  function clearMedia() {
    setMediaPreview(null);
    setHeaderMediaUrl("");
  }

  // Save edits (PATCH)
  async function handleSave() {
    if (!canManageTemplates) {
      setError("Read-only role: resubmitting templates to Meta is disabled.");
      return;
    }
    if (editBlockers.length) {
      focusFirst(editBlockers);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const authHeaders = await getAuthHeaders();
      const payload = {
        body_text: bodyText.trim(),
        body_examples: detectVariables(bodyText).map((n) => (bodySamples[n] ?? "").trim()),
        header_text: headerType === "TEXT" ? headerText.trim() : null,
        header_example: headerVars.length === 1 ? headerSample.trim() : null,
        header_media_type: headerType !== "NONE" && headerType !== "TEXT" ? headerType : null,
        header_media_url: headerType !== "NONE" && headerType !== "TEXT" ? headerMediaUrl : null,
        footer_text: footerText.trim() || null,
        buttons: buttons.length > 0 ? buttons : null,
      };

      const res = await fetch(`${API_URL}/api/v1/templates/${templateId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const text = await res.text();
        let detail = text;
        try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text */ }
        throw new Error(detail || "Failed to save template edits");
      }

      setEditMode(false);
      await loadTemplate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save changes");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto py-12 text-center">
        <RefreshCw size={32} className="animate-spin text-emerald-600 mx-auto mb-4" />
        <p className="font-body text-ink-muted">Loading template details...</p>
      </div>
    );
  }

  if (!template) {
    return (
      <div className="max-w-6xl mx-auto py-12">
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700">
          Template not found or has been deleted.
        </div>
        <Link href="/dashboard/templates" className="mt-4 inline-flex items-center gap-1.5 text-sm text-emerald-600 font-medium">
          <ArrowLeft size={16} /> Back to Templates
        </Link>
      </div>
    );
  }

  // The statuses Meta lets you edit. Approved ones: once per 24 hours, 10 times in 30 days.
  // A template Meta never received (no meta_template_id) can always be edited:
  // saving sends it to Meta for the first time.
  const isEditable = canManageTemplates && (["APPROVED", "REJECTED", "PAUSED"].includes(template.status) || !template.meta_template_id);
  // Meta's limit for approved templates: 1 edit per 24 hours, 10 per 30 days.
  const allowance = template.status === "APPROVED" ? template.edit_allowance : undefined;
  const editBlocked = !!allowance && !allowance.allowed;
  const sc = STATUS_COLORS[template.status] || { bg: "bg-gray-100", text: "text-gray-600", dot: "bg-gray-400" };

  return (
    <div className="max-w-6xl mx-auto pb-12">
      {/* Back navigation & Quick status */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard/templates"
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl hover:bg-[#f1f5f9] text-[#0A1528]/80 hover:text-[#0A1528] font-label text-sm font-semibold transition-all border border-[#e2e8f0] bg-transparent"
          >
            <ArrowLeft size={14} /> Back to Templates
          </Link>
          <div className="h-6 w-[1px] bg-[#e2e8f0]" />
          <div className="flex items-center gap-4">
          <div>
            <h1 className="font-mono text-sm font-semibold text-ink-secondary leading-tight truncate max-w-md">
              {template.name}
            </h1>
            <div className="flex items-center gap-2 mt-1">
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${sc.bg} ${sc.text}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`} />
                {template.status}
              </span>
              <span className="font-body text-xs text-ink-muted">
                {LANGUAGES.find((l) => l.code === template.language)?.label || template.language}
              </span>
              <span className="font-body text-xs text-ink-muted">
                • {template.category}
              </span>
            </div>
          </div>
          <AiraId code={template.short_code} size="lg" className="shrink-0" />
          </div>
        </div>

        {/* Action button bar */}
        <div className="flex items-center gap-2">
          {/* Sync */}
          <button
            onClick={handleSync}
            disabled={syncing || !canManageTemplates}
            className="btn-ghost flex items-center gap-1 text-xs"
            title={canManageTemplates ? "Pull latest approval status from Meta" : "Read-only role: sync is disabled"}
          >
            <RefreshCw size={13} className={syncing ? "animate-spin" : ""} />
            {syncing ? "Syncing..." : "Sync Status"}
          </button>

          {/* Edit toggle (approved, rejected or paused -- what Meta allows) */}
          {isEditable && !editMode && (
            <button
              onClick={() => setEditMode(true)}
              disabled={editBlocked}
              title={editBlocked ? "Meta's edit limit for this template is reached" : undefined}
              className="btn-ghost flex items-center gap-1 text-xs text-emerald-600 hover:bg-emerald-50 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            >
              <Edit3 size={13} />
              Edit Template
            </button>
          )}

          {/* Delete */}
          {canManageTemplates && (
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="btn-ghost flex items-center gap-1 text-xs text-red-600 hover:bg-red-50"
            >
              <Trash2 size={13} />
              Delete
            </button>
          )}

          {/* Send Broadcast (only if approved) */}
          {template.status === "APPROVED" && (
            <Link
              href={`/dashboard/outbound-leads?template=${encodeURIComponent(template.name)}`}
              className="btn-primary flex items-center gap-1 px-4 py-1.5 text-xs"
            >
              <Send size={12} />
              Use for Broadcast
            </Link>
          )}
        </div>
      </div>

      {canManageTemplates && editBlocked && allowance && (
        <div className="mb-6 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-sm flex items-start gap-2.5">
          <Lock size={16} className="mt-0.5 shrink-0 text-amber-700" />
          <p className="font-body">
            {allowance.reason === "daily"
              ? "Meta allows one edit of an approved template every 24 hours, and this one was edited in the last 24 hours."
              : `Meta's limit of ${allowance.limit_30_days} edits in 30 days is used up for this template.`}{" "}
            You can edit it again from <strong>{formatNextEdit(allowance.next_allowed_at)}</strong> (India time). Until then it keeps working as it is.
          </p>
        </div>
      )}

      {editMode && template.status === "APPROVED" && (
        <div className="mb-6 p-4 rounded-xl bg-sky-50 border border-sky-200 text-sky-900 text-sm flex items-start gap-2.5">
          <Info size={16} className="mt-0.5 shrink-0 text-sky-700" />
          <p className="font-body">
            This template is approved. When you save, your edit is sent to Meta for review, and until Meta approves it
            again it won&apos;t be used anywhere in Anril. Meta allows one edit every 24 hours and {allowance?.limit_30_days ?? 10} in
            30 days{allowance ? ` (used ${allowance.edits_30_days} of ${allowance.limit_30_days} so far)` : ""}. The category can&apos;t change.
          </p>
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm flex items-start gap-2.5">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <p className="font-body">{error}</p>
        </div>
      )}

      {/* Rejection notice banner */}
      {template.rejection_reason && (
        <div className="mb-6 p-4 rounded-2xl bg-red-50 border border-red-200 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-body text-sm font-semibold text-red-800">
              Template Rejection Detail
            </p>
            <p className="font-body text-xs text-red-700 mt-1 leading-relaxed">
              {template.rejection_reason}
            </p>
          </div>
        </div>
      )}

      {/* Main Grid: Details or Editor / Live Preview */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left: View Panel or Edit Form, then the Variables map */}
        <div className="lg:col-span-7 space-y-6">
        <div className="bg-white rounded-3xl border border-border-subtle p-6 shadow-sm min-h-[400px]">
          {editMode ? (
            <div className="space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-3">
                <h2 className="font-display text-base font-bold text-ink">
                  {template.status === "APPROVED" ? "Edit Template" : template.status === "PAUSED" ? "Edit Paused Template" : "Edit Rejected Template"}
                </h2>
                <button
                  onClick={() => setEditMode(false)}
                  className="p-1 hover:bg-surface-subtle rounded-lg text-ink-muted"
                >
                  <X size={15} />
                </button>
              </div>

              {/* Header type */}
              {template.category !== "AUTHENTICATION" ? (
                <div>
                  <label className="font-body text-sm font-medium text-ink mb-1.5 block">
                    Header Type
                  </label>
                  <Select
                    className="mb-3"
                    value={headerType}
                    onChange={(v) => {
                      setHeaderType(v as "NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT");
                      setHeaderText("");
                      clearMedia();
                    }}
                    options={[
                      { value: "NONE", label: "None" },
                      { value: "TEXT", label: "Text Header" },
                      { value: "IMAGE", label: "Image Header" },
                      { value: "VIDEO", label: "Video Header" },
                      { value: "DOCUMENT", label: "Document Header" },
                    ]}
                  />

                  {headerType === "TEXT" && (
                    <>
                      <input
                        id="template-header"
                        value={headerText}
                        onChange={(e) => {
                          const cleaned = cleanHeader(e.target.value);
                          show("header", cleaned.note);
                          setHeaderText(cleaned.text);
                        }}
                        maxLength={60}
                        placeholder="e.g. Special Offer"
                        aria-describedby="template-header-messages"
                        aria-invalid={headerBlockers(headerText, "template-header").length > 0}
                        className="input"
                      />
                      <FieldMessages
                        id="template-header-messages"
                        note={notes.header}
                        blockers={headerBlockers(headerText, "template-header")}
                      />
                      {headerVars.length === 1 && (
                        <>
                          <SampleInputs
                            variables={[1]}
                            samples={{ 1: headerSample }}
                            onChange={(next) => setHeaderSample(next[1] ?? "")}
                            idPrefix="template-header-sample-"
                            label="Variable sample"
                            chipLabel={() => "Header {{1}}"}
                          />
                          <FieldMessages
                            id="template-header-sample-messages"
                            blockers={editBlockers.filter((b) => b.fieldId === "template-header-sample-1")}
                          />
                        </>
                      )}
                    </>
                  )}

                  {["IMAGE", "VIDEO", "DOCUMENT"].includes(headerType) && (
                    <div className="mt-3">
                      {headerMediaUrl ? (
                        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <FileCode size={16} className="text-emerald-600" />
                            <span className="font-body text-xs text-emerald-800 font-medium truncate max-w-xs">
                              Media file uploaded
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={clearMedia}
                            className="p-1 hover:bg-emerald-100 rounded-lg text-emerald-600"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <div>
                          <label className="border-2 border-dashed border-border-subtle rounded-2xl p-6 text-center cursor-pointer hover:border-emerald-500/50 hover:bg-emerald-50/50 transition-colors block relative">
                            <input
                              type="file"
                              accept={
                                headerType === "IMAGE"
                                  ? "image/jpeg,image/png,image/webp"
                                  : headerType === "VIDEO"
                                    ? "video/mp4"
                                    : ".pdf,.doc,.docx"
                              }
                              onChange={handleFileSelect}
                              id="template-header-upload"
                              className="sr-only"
                            />
                            <Upload size={24} className="mx-auto text-ink-muted mb-2" />
                            <p className="font-body text-xs text-ink-secondary font-medium">
                              {uploadingMedia ? "Uploading..." : `Upload new header ${headerType.toLowerCase()}`}
                            </p>
                          </label>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-4 bg-surface-subtle border border-border-subtle rounded-2xl flex items-start gap-2">
                  <Lock size={14} className="text-ink-muted mt-0.5" />
                  <p className="font-body text-xs text-ink-muted leading-relaxed">
                    Authentication template structures do not support header text or media formats.
                  </p>
                </div>
              )}

              {/* Body */}
              <div>
                <VariableInserter
                  label="Message Body"
                  value={bodyText}
                  onChange={setBodyText}
                  samples={bodySamples}
                  onSamplesChange={setBodySamples}
                  rows={6}
                  maxLength={1024}
                  placeholder="Enter message body text..."
                />
              </div>

              {/* Footer */}
              <div>
                <label className="font-body text-sm font-medium text-ink mb-1.5 block">
                  Footer Text
                </label>
                <input
                  id="template-footer"
                  value={footerText}
                  onChange={(e) => {
                    const cleaned = cleanFooter(e.target.value);
                    show("footer", cleaned.note);
                    setFooterText(cleaned.text);
                  }}
                  maxLength={60}
                  placeholder="e.g. Reply STOP to unsubscribe"
                  aria-describedby="template-footer-messages"
                  aria-invalid={footerBlockers(footerText, "template-footer").length > 0}
                  className="input"
                />
                <FieldMessages id="template-footer-messages" note={notes.footer} blockers={footerBlockers(footerText, "template-footer")} />
              </div>

              {/* Buttons */}
              <div className="pt-2">
                <ButtonBuilder
                  buttons={buttons}
                  onChange={setButtons}
                  maxButtons={template.category === "AUTHENTICATION" ? 1 : 10}
                  disableCTA={false}
                />
              </div>

              {/* Save or Cancel */}
              <div className="flex items-center gap-3 pt-6 border-t border-border-subtle justify-end flex-wrap">
                <BlockedReason blockers={editBlockers} />
                <button
                  onClick={() => setEditMode(false)}
                  className="btn-ghost px-5 text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving || editBlockers.length > 0}
                  className="btn-primary px-7 text-sm disabled:opacity-50 disabled:blur-[0.5px] disabled:cursor-not-allowed"
                >
                  {saving ? "Saving Changes..." : "Send edit to Meta for review"}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              <h2 className="font-display text-base font-bold text-ink border-b border-border-subtle pb-3">
                Template Data Configuration
              </h2>

              <div className="space-y-4">
                {/* Meta details */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="font-body text-xs text-ink-muted">Meta Template ID</p>
                    <p className="font-mono text-xs font-semibold text-ink truncate mt-0.5 select-all">
                      {template.meta_template_id || "Not Linked"}
                    </p>
                  </div>
                  <div>
                    <p className="font-body text-xs text-ink-muted">Local ID</p>
                    <p className="font-mono text-xs font-semibold text-ink truncate mt-0.5 select-all">
                      {template.id}
                    </p>
                  </div>
                  <div>
                    <p className="font-body text-xs text-ink-muted">Submitted Date</p>
                    <p className="font-body text-xs font-semibold text-ink mt-0.5">
                      {template.submitted_at
                        ? new Date(template.submitted_at).toLocaleDateString("en-IN", {
                            day: "numeric",
                            month: "long",
                            year: "numeric",
                          })
                        : "N/A"}
                    </p>
                  </div>
                  <div>
                    <p className="font-body text-xs text-ink-muted">Approved Date</p>
                    <p className="font-body text-xs font-semibold text-ink mt-0.5">
                      {template.approved_at
                        ? new Date(template.approved_at).toLocaleDateString("en-IN", {
                            day: "numeric",
                            month: "long",
                            year: "numeric",
                          })
                        : "Not Approved Yet"}
                    </p>
                  </div>
                </div>

                {/* Subsections details */}
                {template.header_text && (
                  <div className="pt-3 border-t border-border-subtle">
                    <p className="font-body text-xs text-ink-muted mb-1">Header text</p>
                    <p className="font-body text-sm text-ink">{template.header_text}</p>
                  </div>
                )}

                {template.header_media_type && (
                  <div className="pt-3 border-t border-border-subtle">
                    <p className="font-body text-xs text-ink-muted mb-1">Media Header</p>
                    <p className="font-body text-sm text-ink">
                      Format: <span className="font-bold text-xs uppercase text-emerald-600">{template.header_media_type}</span>
                    </p>
                  </div>
                )}

                <div className="pt-3 border-t border-border-subtle">
                  <p className="font-body text-xs text-ink-muted mb-1">Message Body</p>
                  <p className="font-body text-sm text-ink whitespace-pre-wrap leading-relaxed select-all">
                    {template.body_text}
                  </p>
                </div>

                {template.footer_text && (
                  <div className="pt-3 border-t border-border-subtle">
                    <p className="font-body text-xs text-ink-muted mb-1">Footer text</p>
                    <p className="font-body text-sm text-ink-muted">{template.footer_text}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {!editMode && (
          <VariableMapEditor
            templateId={template.id}
            bodyText={template.body_text}
            saved={template.variable_map}
            canEdit={canManageTemplates}
            onDraftChange={setMapDraft}
            onSaved={(map) => setTemplate((t) => (t ? { ...t, variable_map: map } : t))}
          />
        )}
        </div>

        {/* Right: Sticky Live Preview */}
        <div className="lg:col-span-5 lg:sticky lg:top-6 space-y-4">
          {/* Removed WhatsApp Live Preview label */}
          <WhatsAppPreview
            headerType={
              editMode
                ? headerType === "NONE" || headerType === "TEXT"
                  ? undefined
                  : headerType
                : (template.header_media_type as "NONE" | "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT" | undefined)
            }
            headerText={editMode ? (headerType === "TEXT" ? headerText : undefined) : template.header_text || undefined}
            headerMediaUrl={editMode ? headerMediaUrl || undefined : template.header_media_url || undefined}
            headerMediaPreview={editMode ? mediaPreview?.url : undefined}
            headerMediaName={editMode ? mediaPreview?.name : undefined}
            bodyText={editMode ? bodyText : template.body_text}
            bodySamples={
              editMode
                ? bodySamples
                : Object.fromEntries(Object.entries(mapDraft).map(([n, f]) => [Number(n), fieldLabel(f)]))
            }
            headerSample={editMode ? headerSample : undefined}
            footerText={editMode ? footerText || undefined : template.footer_text || undefined}
            buttons={
              editMode
                ? buttons.map((b) => ({
                    type: b.type,
                    text: b.type === "ONE_TAP" ? (b.autofill_text || "Autofill") : b.text,
                    url: b.url,
                    phone: b.phone,
                  }))
                : template.buttons?.map((b) => ({
                    type: b.type,
                    text: b.type === "ONE_TAP" ? (b.autofill_text || "Autofill") : b.text,
                    url: b.url,
                    phone: b.phone,
                  })) || []
            }
          />
        </div>
      </div>
    </div>
  );
}
