"use client";
import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";

interface ConfirmModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  tone?: "danger" | "warning" | "primary";
  confirmLabel?: string;
  cancelLabel?: string;
  loading?: boolean;
  loadingLabel?: string;
  details?: { label: string; count: number }[];
  /** When set, the confirm button stays disabled until the user types this
   * exact string — for destructive, hard-to-undo actions. */
  requireTypedConfirmation?: string;
}

const TONE_STYLE: Record<NonNullable<ConfirmModalProps["tone"]>, { icon: string; button: string }> = {
  danger: { icon: "bg-danger/10 text-danger", button: "bg-danger hover:bg-danger/90" },
  warning: { icon: "bg-warning/10 text-warning", button: "bg-warning hover:bg-warning/90" },
  primary: { icon: "bg-primary-muted text-primary", button: "bg-primary hover:bg-primary-dark" },
};

export function ConfirmModal({
  open,
  onClose,
  onConfirm,
  title,
  description,
  tone = "primary",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  loading,
  loadingLabel = "Working…",
  details,
  requireTypedConfirmation,
}: ConfirmModalProps) {
  const [typed, setTyped] = useState("");
  if (!open) return null;

  const style = TONE_STYLE[tone];
  const confirmDisabled = loading || (requireTypedConfirmation !== undefined && typed !== requireTypedConfirmation);

  function handleConfirm() {
    onConfirm();
    setTyped("");
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-dialog flex items-center justify-center p-4">
      <div className="bg-white rounded-card shadow-xl w-full max-w-md p-6 max-h-[85dvh] overflow-y-auto">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center ${style.icon}`}>
              <AlertTriangle size={20} />
            </div>
            <h3 className="text-lg font-bold text-ink">{title}</h3>
          </div>
          <button onClick={onClose} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-ink-muted hover:bg-slate-100 hover:text-ink" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <p className="text-sm text-ink-secondary mb-3 whitespace-pre-line">{description}</p>

        {details && details.length > 0 && (
          <ul className="text-sm text-ink mb-4 space-y-1">
            {details.map(d => (
              <li key={d.label} className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-danger" />
                <span className="font-medium">{d.count.toLocaleString()}</span> {d.label}
              </li>
            ))}
          </ul>
        )}

        {requireTypedConfirmation !== undefined && (
          <>
            <p className="text-sm text-ink-secondary mb-2">
              Type <span className="font-mono font-bold text-ink">{requireTypedConfirmation}</span> to confirm:
            </p>
            <input
              value={typed}
              onChange={e => setTyped(e.target.value)}
              className="w-full border border-border rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-danger/20 focus:border-danger mb-4 font-mono"
              placeholder={requireTypedConfirmation}
            />
          </>
        )}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 border border-border text-sm text-ink-secondary rounded-xl hover:bg-surface-mid transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            onClick={handleConfirm}
            disabled={confirmDisabled}
            className={`flex-1 px-4 py-2.5 text-white text-sm font-medium rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${style.button}`}
          >
            {loading ? loadingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
