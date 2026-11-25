"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Eye,
  FileText,
  Loader2,
  PenLine,
  Phone,
  RefreshCw,
  Scale,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import {
  api,
  API_URL,
  getAuthHeaders,
  type KnowledgeConflictChoice,
  type KnowledgeHunk,
  type KnowledgeReview,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { buildFinalDescription, normalizeText, wordCount } from "./descriptionDiff";
import { HANDOVER_SECTION_KEY, type ProfileResponse } from "./profileSections";
import { CheckTick } from "@/components/ui/controls";

interface Props {
  documentId: string;
  canManage: boolean;
  isOwner: boolean;
  onClose: () => void;
  /** After Apply or Discard succeeded. */
  onFinished: (result: { applied: boolean; descriptionChanged: boolean }) => void;
  /** After a Re-sort was started (the review is rebuilt in the background). */
  onResorted: () => void;
}

type ApiError = Error & { status?: number };

// ─── Small building blocks ────────────────────────────────────────────────────

function Section({
  icon,
  title,
  count,
  subtitle,
  action,
  children,
}: {
  icon: ReactNode;
  title: string;
  count?: number;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-surface-mid bg-white shadow-sm">
      <header className="flex items-start justify-between gap-3 border-b border-surface-mid/70 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {icon}
          </span>
          <div className="min-w-0">
            <h4 className="flex items-center gap-2 font-display text-sm font-bold text-on-surface">
              {title}
              {typeof count === "number" && (
                <span className="rounded-full bg-surface-low px-2 py-0.5 font-label text-[10px] font-bold text-on-surface-muted">
                  {count}
                </span>
              )}
            </h4>
            {subtitle && <p className="mt-0.5 font-body text-xs leading-relaxed text-on-surface-muted">{subtitle}</p>}
          </div>
        </div>
        {action}
      </header>
      <div className="space-y-2.5 px-4 py-3.5 sm:px-5">{children}</div>
    </section>
  );
}

function DiffLine({ text, tone }: { text: string; tone: "add" | "remove" }) {
  const blank = !text.trim();
  return (
    <div
      className={cn(
        "flex gap-2 rounded-md px-2 py-1 font-mono text-[11.5px] leading-relaxed",
        tone === "add" ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800",
      )}
    >
      <span className="select-none font-bold opacity-60">{tone === "add" ? "+" : "−"}</span>
      <span className={cn("min-w-0 whitespace-pre-wrap break-words", tone === "remove" && "line-through decoration-red-300", blank && "italic opacity-60")}>
        {blank ? "(blank line)" : text}
      </span>
    </div>
  );
}

const KIND_LABEL: Record<KnowledgeHunk["kind"], string> = {
  add: "Added",
  change: "Changed",
  remove: "Removed",
};

function HunkCard({ hunk, checked, onToggle, disabled }: { hunk: KnowledgeHunk; checked: boolean; onToggle: () => void; disabled: boolean }) {
  return (
    <label
      className={cn(
        "flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors",
        checked ? "border-primary/40 bg-primary/[0.03]" : "border-surface-mid bg-surface-low/40",
        disabled && "cursor-not-allowed opacity-70",
      )}
    >
      <CheckTick checked={checked} onChange={() => onToggle()} disabled={disabled} size="sm" className="mt-0.5 self-start" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <span className="rounded-md border border-surface-mid bg-white px-1.5 py-0.5 font-label text-[10px] font-bold uppercase tracking-wide text-on-surface-muted">
            {KIND_LABEL[hunk.kind]}
          </span>
          {hunk.touches_client_lines && (
            <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-label text-[10px] font-bold text-amber-800">
              <PenLine size={10} /> Changes something you wrote
            </span>
          )}
        </div>
        {hunk.old_lines.map((line, i) => (
          <DiffLine key={`o${i}`} text={line} tone="remove" />
        ))}
        {hunk.new_lines.map((line, i) => (
          <DiffLine key={`n${i}`} text={line} tone="add" />
        ))}
      </div>
    </label>
  );
}

function Banner({ tone, icon, children }: { tone: "amber" | "red" | "slate"; icon: ReactNode; children: ReactNode }) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 font-body text-xs leading-relaxed",
        tone === "amber" && "border-amber-200 bg-amber-50 text-amber-900",
        tone === "red" && "border-red-200 bg-red-50 text-red-800",
        tone === "slate" && "border-surface-mid bg-surface-low text-on-surface-muted",
      )}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

// ─── Modal ────────────────────────────────────────────────────────────────────

export default function KnowledgeReviewModal({ documentId, canManage, isOwner, onClose, onFinished, onResorted }: Props) {
  const [review, setReview] = useState<KnowledgeReview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [conflictChoices, setConflictChoices] = useState<Record<string, KnowledgeConflictChoice>>({});
  const [acceptedUpdates, setAcceptedUpdates] = useState<Set<string>>(new Set());
  const [stale, setStale] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [showLeftOut, setShowLeftOut] = useState(false);
  const [busy, setBusy] = useState<"apply" | "discard" | "resort" | null>(null);
  const [handoverDismissed, setHandoverDismissed] = useState(false);
  // "Use this line" only records the choice. Saving it before Apply would change the
  // Description under the review and make Apply fail as stale (409), so the write
  // happens after Apply (or Discard) has succeeded.
  const [handoverChosen, setHandoverChosen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.knowledge
      .getReview(documentId)
      .then((r) => {
        if (cancelled) return;
        setReview(r);
        setStale(r.stale);
        // Defaults (spec §5): Anril's changes ticked, except where they touch the client's
        // own lines; conflicts leave both options out; price updates ticked unless the
        // line is the client's own.
        setAccepted(new Set(r.hunks.filter((h) => !h.touches_client_lines).map((h) => h.id)));
        setConflictChoices(Object.fromEntries(r.conflicts.map((c) => [c.id, "none" as const])));
        setAcceptedUpdates(
          new Set(r.fact_disagreements.filter((d) => d.where === "description" && !d.client_line).map((d) => d.id)),
        );
      })
      .catch((e: ApiError) => !cancelled && setLoadError(e.message || "Could not load this review."));
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const finalText = useMemo(
    () =>
      review
        ? buildFinalDescription(review, { acceptedHunkIds: accepted, conflictChoices, acceptedUpdateIds: acceptedUpdates })
        : "",
    [review, accepted, conflictChoices, acceptedUpdates],
  );
  const descChanged = review ? normalizeText(finalText) !== normalizeText(review.base_description) : false;
  const finalWords = wordCount(finalText);
  const overLimit = review ? finalWords > review.soft_word_limit : false;
  // A file that is all look-up facts leaves the Description empty. That used to block
  // Apply (and 422 server-side); since 2026-09-20 it only warns -- the facts go live and
  // Anril answers from them, it just has no identity yet. Warning, not blockReason.
  const emptyResult = review !== null && !finalText.trim();
  const ownerBlocked = descChanged && !isOwner;

  const blockReason = !canManage
    ? "You can view this review, but only someone who manages the knowledge base can apply it."
    : stale
      ? "Your Description changed since this review was prepared. Re-sort to build a fresh one."
      : ownerBlocked
        ? "Only an account owner can apply changes to the Description. Untick the Description changes, or ask an owner."
        : null;

  function toggle(set: Set<string>, id: string, update: (s: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    update(next);
  }

  async function apply() {
    if (!review || blockReason) return;
    setBusy("apply");
    try {
      const res = await api.knowledge.applyReview(documentId, {
        base_version_id: review.base_version_id,
        accepted_hunk_ids: Array.from(accepted),
        conflict_choices: conflictChoices,
        accepted_update_ids: Array.from(acceptedUpdates),
      });
      toast.success(
        res.description_changed
          ? "Applied. Your Description is updated and Anril now looks up this file's facts."
          : emptyResult
            ? "Applied. Anril looks up this file's facts, but still has no Description."
            : "Applied. Anril now looks up this file's facts.",
      );
      const handoverWritten = await saveChosenHandover();
      onFinished({ applied: true, descriptionChanged: res.description_changed || handoverWritten });
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) setStale(true);
      toast.error(err.message || "Could not apply this review.");
    } finally {
      setBusy(null);
    }
  }

  async function discard() {
    setBusy("discard");
    try {
      await api.knowledge.discardReview(documentId);
      toast.success(review?.origin === "upload" ? "File discarded. Nothing was changed." : "Changes discarded. The file keeps working as before.");
      const handoverWritten = await saveChosenHandover();
      onFinished({ applied: false, descriptionChanged: handoverWritten });
    } catch (e) {
      toast.error((e as ApiError).message || "Could not discard this review.");
    } finally {
      setBusy(null);
    }
  }

  // Owner-only: the handover wording lives in the "handover" section of the Description,
  // and PUT /ai-tune/profile is the only write path. Read the current sections, replace
  // that one, write them all back so nothing else changes. Returns true when it saved.
  async function writeHandoverLine(line: string): Promise<boolean> {
    try {
      const auth = await getAuthHeaders();
      const getRes = await fetch(`${API_URL}/api/v1/ai-tune/profile`, { headers: auth });
      if (!getRes.ok) throw new Error("Could not read the profile");
      const profile: ProfileResponse = await getRes.json();
      const sections = Object.fromEntries(profile.sections.map((sec) => [sec.key, sec.text]));
      const putRes = await fetch(`${API_URL}/api/v1/ai-tune/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ sections: { ...sections, [HANDOVER_SECTION_KEY]: line }, other: profile.other }),
      });
      if (putRes.status === 422) {
        toast.error("The contact line was not saved: it would push your profile over its word limit. Shorten another section, then add it.");
        return false;
      }
      if (!putRes.ok) throw new Error("Save failed");
      toast.success("Contact line saved under \u2018What Anril says when it brings in your team\u2019.");
      return true;
    } catch {
      toast.error("The contact line was not saved. Add it from your Description.");
      return false;
    }
  }

  // Runs after Apply or Discard has already succeeded, so it never makes the review stale.
  async function saveChosenHandover(): Promise<boolean> {
    const line = review?.suggested_handover.trim();
    if (!handoverChosen || !line || !isOwner) return false;
    return writeHandoverLine(line);
  }

  async function resort() {
    setBusy("resort");
    try {
      await api.knowledge.resort(documentId);
      toast.success("Sorting this file again. It'll be ready to review in a minute.");
      onResorted();
    } catch (e) {
      toast.error((e as ApiError).message || "Could not start sorting again.");
    } finally {
      setBusy(null);
    }
  }

  const descriptionUpdates = review?.fact_disagreements.filter((d) => d.where === "description") ?? [];
  const fileWarnings = review?.fact_disagreements.filter((d) => d.where === "file") ?? [];

  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/50 p-2 backdrop-blur-sm sm:p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Review sorted file"
        className="flex max-h-[94dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-surface-mid bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-surface-mid bg-surface-low/50 px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <p className="font-label text-[11px] font-bold uppercase tracking-wider text-primary">Review before it goes live</p>
            <h3 className="mt-0.5 truncate font-display text-lg font-bold text-on-surface">
              {review?.document_name || "Loading…"}
            </h3>
            <p className="mt-0.5 font-body text-xs text-on-surface-muted">
              Anril split this file into rules for your Description and facts to look up. Nothing changes until you click Apply.
            </p>
            {review?.replaces_document && (
              <span className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-primary-100 bg-primary-50 px-2.5 py-1 font-label text-[11px] font-semibold text-primary-700">
                <RefreshCw size={11} /> Replaces &ldquo;{review.replaces_document.name}&rdquo;
              </span>
            )}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-on-surface-muted transition-colors hover:bg-surface-mid hover:text-on-surface" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-4 overflow-y-auto bg-surface-low/30 px-4 py-4 sm:px-6">
          {!review && !loadError && (
            <div className="flex items-center justify-center gap-2 py-20 font-body text-sm text-on-surface-muted">
              <Loader2 size={18} className="animate-spin text-primary" /> Loading the review…
            </div>
          )}
          {loadError && (
            <Banner tone="red" icon={<AlertTriangle size={14} />}>
              {loadError}
            </Banner>
          )}

          {review && (
            <>
              {stale && (
                <Banner tone="amber" icon={<RefreshCw size={14} />}>
                  <p className="font-semibold">Your Description changed after this review was prepared.</p>
                  <p>Re-sort the file so the proposal is built on top of your latest Description.</p>
                  {canManage && (
                    <button
                      onClick={resort}
                      disabled={busy !== null}
                      className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 font-label text-xs font-semibold text-white transition-colors hover:bg-amber-700 disabled:opacity-50"
                    >
                      {busy === "resort" ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Re-sort
                    </button>
                  )}
                </Banner>
              )}
              {review.truncated && (
                <Banner tone="amber" icon={<AlertTriangle size={14} />}>
                  Only the first 50,000 characters of this file were read. Split it into smaller files if something is missing.
                </Banner>
              )}

              {/* 1. Description changes */}
              <Section
                icon={<PenLine size={14} />}
                title="Changes to your Description"
                count={review.hunks.length}
                subtitle="Anril reads the Description before every reply. Untick anything you don't want."
                action={
                  review.hunks.length > 1 && canManage ? (
                    <div className="flex shrink-0 gap-1">
                      <button
                        onClick={() => setAccepted(new Set(review.hunks.map((h) => h.id)))}
                        className="rounded-lg border border-surface-mid px-2 py-1 font-label text-[11px] font-semibold text-on-surface-muted hover:bg-surface-low"
                      >
                        All
                      </button>
                      <button
                        onClick={() => setAccepted(new Set())}
                        className="rounded-lg border border-surface-mid px-2 py-1 font-label text-[11px] font-semibold text-on-surface-muted hover:bg-surface-low"
                      >
                        None
                      </button>
                    </div>
                  ) : undefined
                }
              >
                {review.hunks.length === 0 ? (
                  <p className="font-body text-xs text-on-surface-muted">Nothing in this file changes your Description.</p>
                ) : (
                  review.hunks.map((h) => (
                    <HunkCard
                      key={h.id}
                      hunk={h}
                      checked={accepted.has(h.id)}
                      disabled={!canManage}
                      onToggle={() => toggle(accepted, h.id, setAccepted)}
                    />
                  ))
                )}
              </Section>

              {/* Contact line found -- a sentence telling customers how to reach a person.
                  Offered for the profile's "What Anril says when it brings in your team"
                  section, never saved automatically. Owner-only (profile write). */}
              {review.suggested_handover.trim() && !handoverDismissed && (
                <section className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4 sm:p-5">
                  <div className="flex items-start gap-2.5">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
                      <Phone size={14} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <h4 className="font-display text-sm font-bold text-on-surface">Contact line found in this file</h4>
                      <p className="mt-1 font-body text-xs leading-relaxed text-amber-900">
                        This tells customers how to reach a person. Use it as your &ldquo;What Anril says when it
                        brings in your team&rdquo; section? It replaces what is in that section now. It is saved when
                        you apply this review, and you can undo it from the profile history.
                      </p>
                      <p className="mt-2 rounded-lg border border-amber-200 bg-white px-3 py-2 font-mono text-[11.5px] leading-relaxed text-on-surface">
                        {review.suggested_handover}
                      </p>
                      {canManage && (
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <button
                            onClick={() => setHandoverChosen((chosen) => !chosen)}
                            disabled={busy !== null || !isOwner}
                            aria-pressed={handoverChosen}
                            aria-describedby={!isOwner ? "handover-owner-reason" : undefined}
                            className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 font-label text-xs font-semibold text-white transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {handoverChosen && <Check size={12} strokeWidth={3} />}
                            {handoverChosen ? "Chosen. Saves when you apply. Undo" : "Use this line"}
                          </button>
                          {!handoverChosen && (
                            <button
                              onClick={() => setHandoverDismissed(true)}
                              className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 font-label text-xs font-semibold text-amber-800 transition-colors hover:bg-amber-50"
                            >
                              Ignore
                            </button>
                          )}
                          {!isOwner && (
                            <p id="handover-owner-reason" className="font-body text-xs text-amber-900">
                              Only an account owner can change this section. Ask an owner to add this line.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </section>
              )}

              {/* 2. Conflicts */}
              {review.conflicts.length > 0 && (
                <Section
                  icon={<Scale size={14} />}
                  title="These disagree — pick one"
                  count={review.conflicts.length}
                  subtitle="Anril couldn't tell which is right, so neither is in your Description yet."
                >
                  {review.conflicts.map((c) => (
                    <div key={c.id} className="rounded-xl border border-surface-mid bg-surface-low/40 p-3">
                      <p className="mb-2 font-label text-xs font-bold text-on-surface">{c.topic || "Conflicting rules"}</p>
                      <div className="space-y-1.5">
                        {(
                          [
                            ["a", c.option_a, c.source_a],
                            ["b", c.option_b, c.source_b],
                            ["none", "Leave both out", ""],
                          ] as const
                        ).map(([value, text, source]) => (
                          <label
                            key={value}
                            className={cn(
                              "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 transition-colors",
                              conflictChoices[c.id] === value ? "border-primary/40 bg-white" : "border-transparent hover:bg-white/70",
                            )}
                          >
                            <input
                              type="radio"
                              name={`conflict-${c.id}`}
                              checked={conflictChoices[c.id] === value}
                              disabled={!canManage}
                              onChange={() => setConflictChoices((prev) => ({ ...prev, [c.id]: value }))}
                              className="mt-0.5 accent-primary"
                            />
                            <span className="min-w-0 flex-1">
                              <span className={cn("block font-body text-xs", value === "none" ? "italic text-on-surface-muted" : "text-on-surface")}>
                                {text}
                              </span>
                              {source && <span className="font-label text-[10px] font-semibold text-on-surface-muted">From {source}</span>}
                            </span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </Section>
              )}

              {/* 3. Price / fact disagreements */}
              {(descriptionUpdates.length > 0 || fileWarnings.length > 0) && (
                <Section
                  icon={<AlertTriangle size={14} />}
                  title="Prices and facts that changed"
                  count={descriptionUpdates.length + fileWarnings.length}
                  subtitle="This file says something different from what Anril already knows."
                >
                  {descriptionUpdates.map((d) => (
                    <label
                      key={d.id}
                      className={cn(
                        "flex cursor-pointer gap-3 rounded-xl border p-3",
                        acceptedUpdates.has(d.id) ? "border-primary/40 bg-primary/[0.03]" : "border-surface-mid bg-surface-low/40",
                      )}
                    >
                      <CheckTick
                        checked={acceptedUpdates.has(d.id)}
                        disabled={!canManage}
                        onChange={() => toggle(acceptedUpdates, d.id, setAcceptedUpdates)}
                        size="sm"
                        className="mt-0.5 self-start"
                      />
                      <div className="min-w-0 flex-1 space-y-1">
                        <p className="font-body text-xs font-semibold text-on-surface">
                          Your Description still says {d.existing_value}. Update it to {d.new_value}?
                        </p>
                        {d.client_line && (
                          <p className="font-body text-[11px] text-amber-800">You wrote this line yourself, so it isn&apos;t ticked for you.</p>
                        )}
                        <DiffLine text={d.existing_line ?? ""} tone="remove" />
                        <DiffLine text={d.proposed_line ?? ""} tone="add" />
                      </div>
                    </label>
                  ))}
                  {fileWarnings.map((d) => (
                    <Banner key={d.id} tone="amber" icon={<FileText size={14} />}>
                      <span className="font-semibold">&ldquo;{d.document_name}&rdquo; says {d.existing_value}</span>, this file says{" "}
                      {d.new_value}. Anril may quote either one. Replace that file, or edit what Anril looks up from it.
                    </Banner>
                  ))}
                </Section>
              )}

              {/* 4. Facts */}
              <Section
                icon={<BookOpen size={14} />}
                title="What Anril will look up from this file"
                subtitle="Kept word for word. Anril reads these only when a customer asks about them."
              >
                {review.facts ? (
                  <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-surface-mid/80 bg-surface-low/40 p-3 font-mono text-[11.5px] leading-relaxed text-on-surface">
                    {review.facts}
                  </pre>
                ) : (
                  <p className="font-body text-xs text-on-surface-muted">
                    Nothing to look up — this file only contained rules for your Description.
                  </p>
                )}
                {review.unverified.length > 0 && (
                  <Banner tone="amber" icon={<AlertTriangle size={14} />}>
                    <p className="font-semibold">Couldn&apos;t verify — check these yourself</p>
                    <p className="mb-1.5">A number or link in these didn&apos;t match the file word for word, so they were left out.</p>
                    <ul className="list-disc space-y-0.5 pl-4">
                      {review.unverified.map((u, i) => (
                        <li key={i}>{u}</li>
                      ))}
                    </ul>
                  </Banner>
                )}
              </Section>

              {/* 5. Left out */}
              {review.left_out_rules.length > 0 && (
                <Banner tone="slate" icon={<Tag size={14} />}>
                  <p className="font-semibold text-on-surface">These look like rules, but this file is for one campaign only.</p>
                  <p>Your Description applies to every campaign, so they were left out. Add them to the Description by hand if they should apply everywhere.</p>
                </Banner>
              )}
              {review.left_out.length > 0 && (
                <div className="rounded-2xl border border-surface-mid bg-white">
                  <button
                    onClick={() => setShowLeftOut((v) => !v)}
                    className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left sm:px-5"
                  >
                    <span className="flex items-center gap-2 font-display text-sm font-bold text-on-surface">
                      <Trash2 size={14} className="text-on-surface-muted" /> Left out
                      <span className="rounded-full bg-surface-low px-2 py-0.5 font-label text-[10px] font-bold text-on-surface-muted">
                        {review.left_out.length}
                      </span>
                    </span>
                    {showLeftOut ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </button>
                  {showLeftOut && (
                    <div className="space-y-2 border-t border-surface-mid/70 px-4 py-3 sm:px-5">
                      {review.left_out.map((item, i) => (
                        <div key={i} className="rounded-xl bg-surface-low/60 p-3">
                          <p className="mb-1 font-label text-[11px] font-semibold text-on-surface-muted">{item.note}</p>
                          <p className="line-clamp-4 whitespace-pre-wrap font-mono text-[11px] text-on-surface-muted">{item.text}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Preview */}
              <div className="rounded-2xl border border-surface-mid bg-white">
                <button
                  onClick={() => setShowPreview((v) => !v)}
                  className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left sm:px-5"
                >
                  <span className="flex items-center gap-2 font-display text-sm font-bold text-on-surface">
                    <Eye size={14} className="text-primary" /> Preview your Description after Apply
                  </span>
                  {showPreview ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                {showPreview && (
                  <div className="border-t border-surface-mid/70 px-4 py-3 sm:px-5">
                    <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-surface-low/40 p-3 font-mono text-[11.5px] leading-relaxed text-on-surface">
                      {finalText || "(empty)"}
                    </pre>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        {review && (
          <div className="space-y-2.5 border-t border-surface-mid bg-surface-low/50 px-5 pt-3.5 pb-[calc(0.875rem+env(safe-area-inset-bottom,0px))] sm:px-6">
            {emptyResult && !blockReason && (
              <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/70 px-3.5 py-3">
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600" />
                <div className="min-w-0 font-body text-xs leading-relaxed text-amber-900">
                  <p className="font-display text-[13px] font-bold">
                    Your facts will go live, but Anril won&rsquo;t know who you are.
                  </p>
                  <p className="mt-0.5 text-amber-800">
                    This file was all look-up facts — nothing in it describes your business. Anril
                    will answer questions from it, but it has no idea what company it works for.
                    {isOwner
                      ? " You can apply this now and add a short description in the upload box on this page whenever you’re ready."
                      : " You can apply this now; ask an account owner to write a short description — only an owner can."}
                  </p>
                </div>
              </div>
            )}
            {blockReason && (
              <p className="flex items-start gap-1.5 font-body text-xs text-amber-800">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {blockReason}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
              <span className={cn("font-mono text-xs", overLimit ? "font-semibold text-amber-700" : "text-on-surface-muted")}>
                Description after Apply: {finalWords.toLocaleString()} words
                {overLimit && ` — over the ${review.soft_word_limit.toLocaleString()}-word guide`}
              </span>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
                {canManage && (
                  <button
                    onClick={discard}
                    disabled={busy !== null}
                    className="flex min-h-10 items-center justify-center gap-1.5 rounded-xl border border-surface-mid bg-surface px-4 py-2 font-label text-xs font-semibold text-on-surface transition-colors hover:bg-surface-mid disabled:opacity-50"
                  >
                    {busy === "discard" && <Loader2 size={12} className="animate-spin" />}
                    {review.origin === "upload" ? "Discard file" : "Discard changes"}
                  </button>
                )}
                <button
                  onClick={apply}
                  disabled={busy !== null || blockReason !== null}
                  className="flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-5 py-2 font-label text-xs font-semibold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {busy === "apply" ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={3} />}
                  Apply
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
