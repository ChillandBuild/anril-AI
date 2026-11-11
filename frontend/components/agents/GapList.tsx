"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { companionKbApi, type ApiError, type KbGap } from "@/lib/api";
import { BTN_PRIMARY, BTN_SECONDARY, ErrorNote, Field, INPUT, LoadingRows } from "./ui";
import { KbDialog } from "./KbDialog";
import { askedText } from "./collectionRows";
import { BTN_ROW, EmptyNote, errorText, useListHeading } from "./collectionUi";

/**
 * The Missing answers tab. Example: "Do you ship to Singapore?",
 * asked 6 times this month, read by Maya. The owner types an answer or dismisses it.
 */
export function GapList({ collectionId }: { collectionId: string }) {
  const [rows, setRows] = useState<KbGap[] | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [answering, setAnswering] = useState<KbGap | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const { heading, focusHeading } = useListHeading("Missing answers");

  const load = useCallback(() => {
    setError("");
    companionKbApi
      .listGaps(collectionId)
      .then(setRows)
      .catch((e) => setError(errorText(e, "Could not load the missing answers.")));
  }, [collectionId]);
  useEffect(load, [load]);

  const remove = (id: string) => setRows((prev) => (prev ? prev.filter((r) => r.id !== id) : prev));

  const dismiss = async (gap: KbGap) => {
    setBusyId(gap.id);
    setActionError("");
    setStatus("");
    try {
      await companionKbApi.dismissGap(gap.id);
      remove(gap.id);
      setStatus("Dismissed.");
      focusHeading();
    } catch (e) {
      setActionError(errorText(e, "Could not dismiss that. Please try again."));
      if ((e as ApiError).status === 409) load();   // no longer open: show the real list
    } finally {
      setBusyId(null);
    }
  };

  if (error) {
    return (
      <div className="p-4">
        <ErrorNote message={error} onRetry={load} />
      </div>
    );
  }
  if (rows === null) {
    return (
      <div className="p-4">
        <LoadingRows />
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <>
        {heading}
        <EmptyNote
          action={
            <button type="button" className={BTN_ROW} onClick={() => { setRows(null); load(); }}>
              Refresh
            </button>
          }
        >
          Nothing missing. Questions your files cannot answer show up here after 5 asks.
        </EmptyNote>
      </>
    );
  }

  return (
    <div>
      {heading}
      {actionError && (
        <div className="p-4 pb-0">
          <ErrorNote message={actionError} />
        </div>
      )}
      <p className="sr-only" role="status">
        {status}
      </p>
      <ul className="divide-y divide-border-subtle">
        {rows.map((g) => (
          <li key={g.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-1">
              <p className="break-words font-medium text-ink">{g.topic}</p>
              <p className="text-sm text-ink-secondary">
                {askedText(g.ask_count)} · {g.companion_name}
              </p>
              <p className="text-sm text-ink-secondary">Not in your files.</p>
            </div>
            <div className="flex flex-wrap gap-2 sm:justify-end">
              <button type="button" className={BTN_ROW} disabled={busyId === g.id} onClick={() => setAnswering(g)} aria-label={`Type an answer: ${g.topic}`}>
                Type an answer
              </button>
              <button type="button" className={BTN_ROW} disabled={busyId === g.id} onClick={() => dismiss(g)} aria-label={`Dismiss: ${g.topic}`}>
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>

      {answering && (
        <AnswerDialog
          gap={answering}
          onClose={() => setAnswering(null)}
          onStale={load}
          onSaved={() => {
            remove(answering.id);
            setStatus("Answer saved.");
            setAnswering(null);
            focusHeading();
          }}
        />
      )}
    </div>
  );
}

function AnswerDialog({ gap, onClose, onSaved, onStale }: { gap: KbGap; onClose: () => void; onSaved: () => void; onStale: () => void }) {
  const formId = useId();
  const fieldId = useId();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const answer = text.trim();
    if (!answer) {
      setError("Write the answer first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await companionKbApi.answerGap(gap.id, answer);
      onSaved();
    } catch (err) {
      if (mounted.current) {
        setError(errorText(err, "Could not save the answer. Please try again."));
        setBusy(false);
      }
      if ((err as ApiError).status === 409) onStale();   // no longer open: refresh the list behind the dialog
    }
  };

  return (
    <KbDialog
      open
      title="Type an answer"
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <button type="button" className={BTN_SECONDARY} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form={formId} className={BTN_PRIMARY} disabled={busy}>
            {busy ? "Saving…" : "Save answer"}
          </button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="space-y-3">
        <p className="break-words font-medium text-ink">{gap.topic}</p>
        <p className="text-ink-secondary">
          Your answer is saved into this collection, as part of a document called &ldquo;Owner answers&rdquo;. The character uses it from
          the next question.
        </p>
        <Field id={fieldId} label="Your answer" error={error}>
          <textarea
            id={fieldId}
            data-autofocus
            rows={6}
            maxLength={4000}
            className={INPUT}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Write the answer in your own words"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldId}-error` : undefined}
          />
        </Field>
      </form>
    </KbDialog>
  );
}
