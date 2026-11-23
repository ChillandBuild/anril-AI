"use client";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { aiSetupApi, FEEDBACK_REASONS, type FeedbackReason } from "@/lib/aiSetupApi";
import { replyMarks } from "@/components/ai-setup/replyMarks";

/** A small thumbs-down on one AI reply, with a reason. Saved so it counts on the AI report card. */
export function ReplyFeedback({ messageId }: { messageId: string }) {
  const [step, setStep] = useState<"idle" | "pick" | "done">("idle");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState<FeedbackReason>("wrong");
  const [note, setNote] = useState("");

  // A mark this person left earlier (before a reload) shows again, with Undo. One call covers every reply on screen.
  useEffect(() => {
    let alive = true;
    void replyMarks.get(messageId).then((mark) => {
      if (!alive || !mark) return;
      setReason(mark.reason);
      setNote(mark.note ?? "");
      setStep("done");
    });
    return () => { alive = false; };
  }, [messageId]);

  async function send() {
    if (busy) return;
    setBusy(true);
    try {
      await aiSetupApi.thumbsDown(messageId, reason, note);
      replyMarks.set(messageId, { reason, note: note.trim() || null });
      setStep("done");
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not save that. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (busy) return;
    setBusy(true);
    try {
      await aiSetupApi.undoThumbsDown(messageId);
      replyMarks.set(messageId, null);
      setStep("idle");
      setNote("");
    } catch {
      toast.error("Could not undo that. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    const label = FEEDBACK_REASONS.find((r) => r.value === reason)?.label;
    return (
      <p className="mt-1 font-body text-xs text-[#556274]">
        Noted, thank you{label ? `: ${label}` : ""}. <button type="button" onClick={undo} disabled={busy} className="font-semibold text-primary underline">Undo</button>
      </p>
    );
  }
  if (step === "pick") {
    return (
      <div className="mt-2 space-y-2 rounded-xl border border-[#e2e8f0] bg-white p-2.5">
        <p className="font-label text-xs font-bold text-[#0A1528]">What was wrong with this reply?</p>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Reason">
          {FEEDBACK_REASONS.map((r) => (
            <button key={r.value} type="button" aria-pressed={reason === r.value} onClick={() => setReason(r.value)}
              className={`min-h-8 rounded-full border px-2.5 font-label text-xs font-bold ${
                reason === r.value ? "border-primary bg-primary text-white" : "border-[#e2e8f0] bg-white text-[#0A1528]"}`}>
              {r.label}
            </button>
          ))}
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} aria-label="Add a note (optional)"
          placeholder="Add a note (optional)"
          className="w-full rounded-lg border border-[#e2e8f0] px-2.5 py-1.5 font-body text-xs text-[#0A1528] focus:outline-none focus:ring-2 focus:ring-primary/20" />
        <div className="flex gap-2">
          <button type="button" onClick={send} disabled={busy} className="btn-primary min-h-8 disabled:opacity-50">Send</button>
          <button type="button" onClick={() => setStep("idle")} className="min-h-8 rounded-lg border border-[#e2e8f0] bg-white px-3 font-label text-xs font-bold text-[#0A1528]">Cancel</button>
        </div>
      </div>
    );
  }
  return (
    <button type="button" onClick={() => setStep("pick")} aria-label="Mark this AI reply as bad"
      className="mt-1 inline-flex min-h-7 items-center rounded-md px-1.5 text-xs text-[#556274] hover:bg-white/70 hover:text-[#0A1528]">
      <span aria-hidden>{"👎"}</span><span className="ml-1 font-label font-semibold">Bad reply?</span>
    </button>
  );
}
