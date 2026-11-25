"use client";
import { useState } from "react";
import { createPortal } from "react-dom";
import { MessageSquarePlus, X } from "lucide-react";
import { API_URL, getAuthHeaders } from "@/lib/api";

const MESSAGE_MAX = 2000;

export function FeedbackModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleSubmit() {
    const trimmed = message.trim();
    if (!trimmed) return;
    setState("saving");
    setError(null);
    try {
      const auth = await getAuthHeaders();
      const res = await fetch(`${API_URL}/api/v1/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ message: trimmed }),
      });
      if (!res.ok) throw new Error("Failed to submit feedback");
      setState("sent");
      setMessage("");
    } catch {
      setError("Couldn't send that — try again.");
      setState("idle");
    }
  }

  function handleClose() {
    setState("idle");
    setError(null);
    setMessage("");
    onClose();
  }

  // Drawn on <body>: the header that opens this modal is fixed, so an inline overlay sat under the bottom bar.
  const overlay = (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-card bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-muted text-primary">
              <MessageSquarePlus size={18} />
            </div>
            <h3 className="text-lg font-bold text-ink">Feedback</h3>
          </div>
          <button onClick={handleClose} className="text-ink-muted hover:text-ink" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {state === "sent" ? (
          <p className="py-4 text-sm text-ink-secondary">Thanks — that&apos;s on its way to the team.</p>
        ) : (
          <>
            <p className="mb-3 text-sm text-ink-secondary">What&apos;s working, what&apos;s not — tell us anything.</p>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={4}
              maxLength={MESSAGE_MAX}
              placeholder="Type your feedback…"
              className="mb-2 w-full rounded-xl border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            {error && <p className="mb-2 text-sm text-danger">{error}</p>}
            <div className="flex gap-3">
              <button
                onClick={handleClose}
                className="flex-1 rounded-xl border border-border px-4 py-2.5 text-sm text-ink-secondary transition-colors hover:bg-surface-mid"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={!message.trim() || state === "saving"}
                className="flex-1 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-40"
              >
                {state === "saving" ? "Sending…" : "Send"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
  return typeof document === "undefined" ? null : createPortal(overlay, document.body);
}
