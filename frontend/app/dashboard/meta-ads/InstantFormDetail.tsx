"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, Check, Download, FileText, Search } from "lucide-react";
import { toast } from "sonner";
import { Select } from "@/components/ui/Select";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useInstantForm, useInstantFormLeads, useInstantFormTemplates } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type {
  InstantFormDetail as InstantFormDetailData,
  InstantFormLead,
  InstantFormQuestion,
  InstantFormRange,
  InstantFormTemplateOption,
  InstantFormVariable,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { DatesMenu, TOOLBAR_BUTTON } from "./reportControls";
import {
  FormStatusBadge,
  InstantFormStatCards,
  LoadErrorCard,
  StatCardsSkeleton,
  TEMPLATE_STATUS,
  TemplateStatusBadge,
  dateText,
  dateTimeText,
  errorMessage,
  localDate,
} from "./instantFormsShared";

const PAGE_SIZE = 50;
const EXPORT_PAGE_SIZE = 500;
const MAX_FIXED_TEXT = 200;
/** Answers to these get their own columns; every other question gets one of its own. */
const STANDARD_KEYS = new Set(["full_name", "first_name", "last_name", "phone_number", "email"]);
/** Leads where a send can be tried again from the table. */
const CAN_SEND_AGAIN = new Set(["failed", "no_template", "skipped_old"]);

const FIRST_NAME = "field:first_name";
const FIXED_TEXT = "text";

const PRIMARY_BUTTON =
  "inline-flex h-9 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 font-label text-xs font-bold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-40";

/** One blank's choice in the editor: "field:<key>", "field:first_name" or "text". */
type DraftVariable = { choice: string; text: string };

function questionLabel(question: InstantFormQuestion): string {
  return question.label || question.key;
}

/** The starting choice for blank n when nothing is saved: blank 1 is the first name, the rest fixed text. */
function draftFor(saved: InstantFormVariable | undefined, index: number): DraftVariable {
  if (!saved) return { choice: index === 0 ? FIRST_NAME : FIXED_TEXT, text: "" };
  return saved.source === "field"
    ? { choice: `field:${saved.field}`, text: "" }
    : { choice: FIXED_TEXT, text: saved.text };
}

function toVariable(draft: DraftVariable): InstantFormVariable {
  if (draft.choice === FIXED_TEXT) return { source: "text", text: draft.text };
  return { source: "field", field: draft.choice.slice("field:".length) };
}

/** A key-order-proof string for comparing a saved blank list with the editor's. */
function variableSignature(variables: InstantFormVariable[]): string {
  return variables.map((variable) => (variable.source === "field" ? `field:${variable.field}` : `text:${variable.text}`)).join("|");
}

function describeVariable(variable: InstantFormVariable, questions: InstantFormQuestion[]): string {
  if (variable.source === "text") return `Fixed text: "${variable.text}"`;
  if (variable.field === "first_name") return "First name";
  const question = questions.find((item) => item.key === variable.field);
  return question ? questionLabel(question) : variable.field;
}

/** Each {{n}} in the body is highlighted so it's clear where the values go. */
function highlightBody(text: string): ReactNode[] {
  return text.split(/(\{\{\d+\}\})/g).map((part, index) =>
    /^\{\{\d+\}\}$/.test(part) ? (
      <mark key={index} className="rounded bg-primary-100 px-1 font-label text-xs font-bold text-primary-800">
        {part}
      </mark>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}

/** The message as the person gets it: the header (image, video, document or text), then the body. */
function TemplatePreview({ template }: { template: InstantFormTemplateOption }) {
  const media = template.header_media_type;
  return (
    <div className="overflow-hidden rounded-xl bg-[#f8fafc]">
      {media === "IMAGE" && template.header_media_url && (
        // eslint-disable-next-line @next/next/no-img-element -- template files live on Supabase Storage, not a configured Next image domain
        <img src={template.header_media_url} alt="Template header" className="max-h-48 w-full object-cover" />
      )}
      {media === "VIDEO" && template.header_media_url && (
        <video src={template.header_media_url} controls preload="metadata" className="max-h-48 w-full bg-black" />
      )}
      {media === "DOCUMENT" && (
        <div className="flex items-center gap-2 border-b border-[#e2e8f0] px-3.5 py-2.5 font-label text-xs font-bold text-[#475569]">
          <FileText size={14} aria-hidden="true" />
          {template.header_media_url ? (
            <a href={template.header_media_url} target="_blank" rel="noreferrer" className="text-primary-700 hover:text-primary-900">
              Document attached
            </a>
          ) : (
            "Document attached"
          )}
        </div>
      )}
      <div className="p-3.5 font-body text-sm leading-relaxed whitespace-pre-wrap text-on-surface">
        {media === "TEXT" && template.header_text && (
          <p className="mb-1.5 font-label font-bold text-[#0A1528]">{template.header_text}</p>
        )}
        {highlightBody(template.body_text)}
      </div>
    </div>
  );
}

function answerText(lead: InstantFormLead, key: string): string {
  return lead.answers.find((answer) => answer.name === key)?.values.join(", ") ?? "";
}

function csvCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function buildCsv(detail: InstantFormDetailData, leads: InstantFormLead[]): string {
  const header = [
    "Submitted",
    "Name",
    "Phone",
    "Email",
    ...detail.questions.map(questionLabel),
    "Ad",
    "Ad set",
    "Campaign",
    "Organic",
    "WhatsApp status",
  ];
  const lines = leads.map((lead) => [
    dateTimeText(lead.meta_created_at),
    lead.name ?? "",
    lead.phone ?? "",
    lead.email ?? "",
    ...detail.questions.map((question) => answerText(lead, question.key)),
    lead.ad_name ?? "",
    lead.adset_name ?? "",
    lead.campaign_name ?? "",
    lead.is_organic ? "Yes" : "No",
    TEMPLATE_STATUS[lead.template_status]?.label ?? lead.template_status,
  ]);
  return [header, ...lines].map((line) => line.map(csvCell).join(",")).join("\r\n");
}

function fileSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "form";
}

export function InstantFormDetail({ formId }: { formId: string }) {
  const { role, permissions } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("meta_ads.manage");
  const [dateFrom, setDateFrom] = useState(() => localDate(29));
  const [dateTo, setDateTo] = useState(() => localDate());
  const range: InstantFormRange = { date_from: dateFrom, date_to: dateTo };

  const { data: detail, error: detailError, mutate: mutateDetail } = useInstantForm(formId, range);
  const { data: templateData, error: templatesError } = useInstantFormTemplates();
  const templates = templateData?.data ?? [];

  // WhatsApp message editor state. It follows the saved setup until someone edits it.
  const [templateId, setTemplateId] = useState("");
  const [draft, setDraft] = useState<DraftVariable[]>([]);
  const [syncedKey, setSyncedKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const serverKey = detail ? JSON.stringify([detail.template_id, detail.template_variables]) : null;
  if (detail && serverKey !== syncedKey) {
    setSyncedKey(serverKey);
    setTemplateId(detail.template_id ?? "");
    setDraft(detail.template_variables.map((variable, index) => draftFor(variable, index)));
  }
  const selected = templates.find((template) => template.id === templateId);
  const blanks = selected?.blanks ?? 0;
  const rows: DraftVariable[] = Array.from({ length: blanks }, (_, index) => draft[index] ?? draftFor(undefined, index));
  const invalidText = rows.some((row) => row.choice === FIXED_TEXT && !row.text.trim());
  const variables: InstantFormVariable[] = templateId && selected ? rows.map(toVariable) : [];
  const savedTemplate = detail?.template_id ?? null;
  const savedVariables = savedTemplate ? detail?.template_variables ?? [] : [];
  const dirty = (templateId || null) !== savedTemplate || variableSignature(variables) !== variableSignature(savedVariables);
  const canSave = canManage && dirty && !saving && !invalidText && (!templateId || Boolean(selected));

  // Leads table: search is debounced, and any change of search or dates goes back to page 1.
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: leads, error: leadsError, mutate: mutateLeads } = useInstantFormLeads(formId, {
    ...range,
    search: query || undefined,
    page,
    limit: PAGE_SIZE,
  });
  const total = leads?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);
  const questionColumns = (detail?.questions ?? []).filter((question) => !STANDARD_KEYS.has(question.key));

  function changeRange(from: string, to: string) {
    setDateFrom(from);
    setDateTo(to);
    setPage(1);
  }

  function pickTemplate(id: string) {
    setTemplateId(id);
    setDraft([]);
  }

  function changeRow(index: number, next: DraftVariable) {
    setDraft(rows.map((row, position) => (position === index ? next : row)));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await api.instantForms.setTemplate(formId, templateId || null, variables);
      toast.success("Saved. New leads from this form get this message.");
      await mutateDetail();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function handleSend(lead: InstantFormLead) {
    setSendingId(lead.id);
    try {
      const result = await api.instantForms.sendTemplate(lead.id);
      if (result.template_status === "sent") toast.success("Sent");
      else if (result.template_status === "no_template") toast.error("Choose a WhatsApp message for this form first.");
      else toast.error(result.template_error || "Not sent");
      await Promise.all([mutateLeads(), mutateDetail()]);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setSendingId(null);
    }
  }

  async function handleDownload() {
    if (!detail) return;
    setExporting(true);
    try {
      const all: InstantFormLead[] = [];
      let current = 1;
      let expected = Number.POSITIVE_INFINITY;
      while (all.length < expected) {
        const response = await api.instantForms.leads(formId, {
          ...range,
          search: query || undefined,
          page: current,
          limit: EXPORT_PAGE_SIZE,
        });
        expected = response.total;
        all.push(...response.data);
        if (response.data.length === 0) break;
        current += 1;
      }
      const csv = buildCsv(detail, all);
      // The byte-order mark makes Excel read UTF-8, so Tamil and Hindi names stay readable.
      const url = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `instant-form-${fileSlug(detail.name)}-${dateFrom}-to-${dateTo}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setExporting(false);
    }
  }

  function renderMessageCard() {
    return (
      <section aria-label="WhatsApp message" className="flex flex-col gap-4 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
        <div>
          <h2 className="font-label text-sm font-bold text-[#0A1528]">WhatsApp message</h2>
          <p className="mt-1 font-body text-xs leading-relaxed text-[#64748b]">
            Sent on WhatsApp the moment someone fills this form. Any approved template works, including ones with an image, video or document.
          </p>
        </div>

        {canManage ? (
          <>
            <label className="flex flex-col gap-1.5 font-label text-[11px] font-bold uppercase tracking-wider text-[#64748b]">
              Template
              <Select
                value={templateId}
                onChange={pickTemplate}
                className="normal-case tracking-normal"
                options={[
                  { value: "", label: "Don't send anything" },
                  ...templates.map((template) => ({
                    value: template.id,
                    label: `${template.name} (${template.language})`,
                  })),
                ]}
              />
            </label>
            {templatesError && (
              <p className="font-body text-xs text-red-600">{errorMessage(templatesError)}</p>
            )}
            {templateData && savedTemplate && !templates.some((template) => template.id === savedTemplate) && (
              <p className="rounded-xl bg-amber-50 px-3 py-2 font-body text-xs text-amber-800">
                The template this form used isn&apos;t approved on your WhatsApp number any more, so new leads get no message. Pick another one and save.
              </p>
            )}
            {!templatesError && templates.length === 0 && (
              <p className="font-body text-xs text-[#64748b]">
                No approved templates yet.{" "}
                <Link href="/dashboard/templates" className="font-bold text-primary-700 hover:text-primary-900">
                  Open templates
                </Link>
              </p>
            )}

            {selected && (
              <>
                <TemplatePreview template={selected} />
                <div className="flex flex-col gap-2.5">
                  {rows.map((row, index) => (
                    <div key={index} className="flex flex-wrap items-center gap-2">
                      <span className="w-16 font-label text-xs font-bold text-primary-700">{`{{${index + 1}}}`}</span>
                      <Select
                        size="sm"
                        aria-label={`Value for {{${index + 1}}}`}
                        value={row.choice}
                        onChange={(v) => changeRow(index, { choice: v, text: row.text })}
                        className="min-w-[180px] flex-1"
                        options={[
                          { value: FIRST_NAME, label: "First name" },
                          ...(detail?.questions ?? []).map((question) => ({
                            value: `field:${question.key}`,
                            label: questionLabel(question),
                          })),
                          { value: FIXED_TEXT, label: "Fixed text…" },
                        ]}
                      />
                      {row.choice === FIXED_TEXT && (
                        <input
                          type="text"
                          value={row.text}
                          maxLength={MAX_FIXED_TEXT}
                          onChange={(event) => changeRow(index, { choice: FIXED_TEXT, text: event.target.value })}
                          placeholder="Type the text"
                          aria-label={`Fixed text for {{${index + 1}}}`}
                          className="h-9 min-w-[180px] flex-1 rounded-xl border border-[#e2e8f0] bg-white px-3 font-body text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
                        />
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-[#eef2f6] pt-4">
              <p className="font-body text-[11px] text-[#94a3b8]">
                {invalidText ? "Fixed text can't be empty." : dirty ? "You have unsaved changes." : "Saved."}
              </p>
              <button type="button" onClick={handleSave} disabled={!canSave} className={PRIMARY_BUTTON}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </>
        ) : (
          <div className="flex flex-col gap-3">
            {selected && detail?.template_id ? (
              <>
                <p className="font-label text-sm font-bold text-[#0A1528]">{`${selected.name} (${selected.language})`}</p>
                <TemplatePreview template={selected} />
                <ul className="flex flex-col gap-1.5 font-body text-xs text-[#475569]">
                  {detail.template_variables.map((variable, index) => (
                    <li key={index}>
                      <span className="font-label font-bold text-primary-700">{`{{${index + 1}}}`}</span>{" "}
                      {describeVariable(variable, detail.questions)}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="font-body text-sm text-[#64748b]">No WhatsApp message is set for this form.</p>
            )}
            <p className="font-body text-[11px] text-[#94a3b8]">Ask an admin to change this.</p>
          </div>
        )}
      </section>
    );
  }

  function renderLeadRows() {
    if (!leads) {
      return (
        <tbody className="divide-y divide-[#f1f5f9]">
          {Array.from({ length: 6 }, (_, index) => (
            <tr key={index}>
              {Array.from({ length: 8 }, (__, cell) => (
                <td key={cell} className="px-4 py-3">
                  <div className="h-3 w-full max-w-[120px] animate-pulse rounded bg-stone-200/70" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      );
    }
    return (
      <tbody className="divide-y divide-[#f1f5f9]">
        {leads.data.map((lead) => {
          const canSend = canManage && Boolean(lead.phone) && CAN_SEND_AGAIN.has(lead.template_status);
          return (
            <tr key={lead.id} className="group transition-colors hover:bg-[#f8fafc]">
              <td className="whitespace-nowrap px-4 py-3 text-xs text-on-surface-muted">{dateTimeText(lead.meta_created_at)}</td>
              <td className="max-w-[180px] truncate px-4 py-3 font-label text-xs font-semibold text-[#0A1528]" title={lead.name ?? undefined}>{lead.name || "—"}</td>
              <td className="whitespace-nowrap px-4 py-3 text-xs tabular-nums">{lead.phone || "—"}</td>
              <td className="max-w-[200px] truncate px-4 py-3 text-xs" title={lead.email ?? undefined}>{lead.email || "—"}</td>
              {questionColumns.map((question) => (
                <td key={question.key} className="max-w-[200px] truncate px-4 py-3 text-xs" title={answerText(lead, question.key)}>
                  {answerText(lead, question.key) || "—"}
                </td>
              ))}
              <td className="max-w-[200px] px-4 py-3 text-xs">
                {lead.is_organic ? (
                  <span className="font-label font-semibold text-[#475569]">Organic</span>
                ) : (
                  <>
                    <span className="block truncate font-label font-semibold text-[#0A1528]" title={lead.ad_name ?? undefined}>{lead.ad_name || "—"}</span>
                    {lead.campaign_name && (
                      <span className="block truncate text-[11px] text-[#94a3b8]" title={lead.campaign_name}>{lead.campaign_name}</span>
                    )}
                  </>
                )}
              </td>
              <td className="whitespace-nowrap px-4 py-3">
                <TemplateStatusBadge status={lead.template_status} error={lead.template_error} />
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-xs">
                {lead.replied ? (
                  <span className="inline-flex items-center gap-1 font-label font-bold text-emerald-700">
                    <Check size={13} aria-hidden="true" /> Replied
                  </span>
                ) : (
                  <span className="text-[#94a3b8]">—</span>
                )}
              </td>
              {/* Pinned to the right edge so Send / Open lead stay visible however many questions the form has. */}
              <td className="sticky right-0 whitespace-nowrap border-l border-[#f1f5f9] bg-white px-4 py-3 group-hover:bg-[#f8fafc]">
                <div className="flex items-center justify-end gap-2">
                  {canSend && (
                    <button
                      type="button"
                      onClick={() => handleSend(lead)}
                      disabled={sendingId === lead.id}
                      className="h-7 rounded-lg border border-primary-200 bg-primary-50 px-2.5 font-label text-[11px] font-bold text-primary-800 transition-colors hover:bg-primary-100 disabled:opacity-40"
                    >
                      {sendingId === lead.id ? "Sending…" : "Send"}
                    </button>
                  )}
                  {lead.lead_id && (
                    <Link
                      href={`/dashboard/conversations?lead=${encodeURIComponent(lead.lead_id)}`}
                      className="font-label text-[11px] font-bold text-primary-700 hover:text-primary-900"
                    >
                      Open lead
                    </Link>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    );
  }

  return (
    <div className="space-y-[18px]">
      <Link href="/dashboard/meta-ads/instant-forms" className="inline-flex items-center gap-1.5 font-label text-xs font-bold text-primary-700 hover:text-primary-900">
        <ArrowLeft size={13} aria-hidden="true" />
        All forms
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {detail ? (
            <>
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="font-display text-2xl font-extrabold tracking-tight text-[#0A1528]">{detail.name}</h1>
                <FormStatusBadge status={detail.status} />
              </div>
              {detail.created_at && (
                <p className="mt-1 font-body text-xs text-[#64748b]">Created {dateText(detail.created_at)}</p>
              )}
              <p className="font-body text-[11px] text-[#94a3b8]">Form ID {detail.form_id}</p>
            </>
          ) : (
            !detailError && <div className="h-7 w-56 animate-pulse rounded-lg bg-stone-200/70" />
          )}
        </div>
        <DatesMenu
          dateFrom={dateFrom}
          dateTo={dateTo}
          onChange={changeRange}
          canManage={canManage}
          onHistorySaved={() => mutateDetail()}
          historyNote="Spend comes from the same Meta ad data as All ads."
        />
      </div>

      {detailError && !detail ? (
        <LoadErrorCard title="Could not load this form" message={errorMessage(detailError)} onRetry={() => mutateDetail()} />
      ) : (
        <>
          {detail ? (
            <InstantFormStatCards
              stats={detail.stats}
              spendAvailable={detail.spend_available}
              leadsExtra={{ label: "Questions", value: detail.questions.length }}
            />
          ) : (
            <StatCardsSkeleton />
          )}

          <div className="grid grid-cols-1 items-start gap-[18px] lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            {renderMessageCard()}
            <section aria-label="Questions" className="flex flex-col gap-3 rounded-2xl border border-[#e2e8f0] bg-white p-5 shadow-sm">
              <h2 className="font-label text-sm font-bold text-[#0A1528]">Questions</h2>
              {detail && detail.questions.length > 0 ? (
                <ul className="divide-y divide-[#f1f5f9]">
                  {detail.questions.map((question) => (
                    <li key={question.key} className="flex items-center justify-between gap-3 py-2.5">
                      <span className="min-w-0 truncate font-body text-sm text-on-surface" title={questionLabel(question)}>{questionLabel(question)}</span>
                      {question.type && <span className="shrink-0 font-body text-[11px] capitalize text-[#94a3b8]">{question.type.replace(/_/g, " ").toLowerCase()}</span>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="font-body text-xs text-[#94a3b8]">{detail ? "This form has no questions." : "Loading…"}</p>
              )}
            </section>
          </div>

          <section aria-label="Leads" className="overflow-hidden rounded-2xl border border-[#e2e8f0] bg-white shadow-sm">
            <div className="flex flex-wrap items-center gap-2 border-b border-[#eef2f6] p-3.5">
              <label className="relative min-w-[200px] max-w-[320px] flex-1">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search name, phone or email"
                  aria-label="Search leads"
                  className="h-9 w-full rounded-xl border border-[#e2e8f0] bg-[#f8fafc] pl-9 pr-3 font-body text-xs font-medium text-on-surface focus:outline-none focus:ring-2 focus:ring-primary-200"
                />
              </label>
              <span className="hidden flex-1 md:block" />
              <button
                type="button"
                onClick={handleDownload}
                disabled={!detail || exporting || total === 0}
                className={cn(TOOLBAR_BUTTON)}
              >
                <Download size={13} />
                {exporting ? "Preparing…" : "Download CSV"}
              </button>
            </div>

            <div className="overflow-hidden rounded-b-2xl">
              {leadsError && !leads ? (
                <div className="p-4">
                  <LoadErrorCard title="Could not load leads" message={errorMessage(leadsError)} onRetry={() => mutateLeads()} />
                </div>
              ) : leads && leads.data.length === 0 ? (
                <p className="px-4 py-16 text-center font-body text-sm text-[#94a3b8]">No leads in these dates.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[960px]">
                    <thead>
                      <tr className="border-b border-[#eef2f6]">
                        {["Submitted", "Name", "Phone", "Email", ...questionColumns.map(questionLabel), "Ad", "WhatsApp", "Replied", ""].map((heading, index) => (
                          <th
                            key={`${heading}-${index}`}
                            className={cn(
                              "whitespace-nowrap px-4 py-3 text-left font-label text-[10px] font-bold uppercase tracking-wider text-on-surface-muted",
                              heading === "" && "sticky right-0 border-l border-[#f1f5f9] bg-white",
                            )}
                          >
                            {heading}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    {renderLeadRows()}
                  </table>
                </div>
              )}
            </div>

            {leads && total > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#eef2f6] px-4 py-3">
                <span className="font-body text-[11px] text-[#64748b]">{`Showing ${from}–${to} of ${total}`}</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                    disabled={page <= 1}
                    className={TOOLBAR_BUTTON}
                  >
                    Previous
                  </button>
                  <span className="font-label text-[11px] font-bold tabular-nums text-[#475569]">{`${page} / ${lastPage}`}</span>
                  <button
                    type="button"
                    onClick={() => setPage((current) => Math.min(lastPage, current + 1))}
                    disabled={page >= lastPage}
                    className={TOOLBAR_BUTTON}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
