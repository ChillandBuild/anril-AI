"use client";
import { useState } from "react";
import { Archive, Trash2 } from "lucide-react";
import { companionsApi, type Companion } from "@/lib/api";
import { nameMatches } from "@/components/agents/characterForm";
import { cn } from "@/lib/utils";
import { KbDialog } from "@/components/agents/KbDialog";
import { BTN_DANGER, BTN_PRIMARY, BTN_SECONDARY, INPUT } from "@/components/agents/ui";

export type DeleteChoice = "archive" | "delete";

/**
 * The Delete popup for one character. Two choices:
 * - Archive: hidden from the list, stops answering, chats and memory kept. Restore any time (comes back as Draft).
 * - Delete permanently: gone with its chats and memory. For a Live character you type its name first.
 * Example: Jothidar AI (Live) → pick "Delete permanently" → type "Jothidar AI" → the red button unlocks.
 * `only="delete"` is the Archived tab's button: the character is already archived, so just the permanent choice.
 */
export function CharacterDeleteDialog({
  character,
  only,
  onClose,
  onDone,
}: {
  character: Companion;
  only?: "delete";
  onClose: () => void;
  onDone: (choice: DeleteChoice) => void;
}) {
  const [choice, setChoice] = useState<DeleteChoice>(only ?? "archive");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const needsName = choice === "delete" && character.status === "live";
  const ready = !needsName || nameMatches(typed, character.name);

  const confirm = async () => {
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      if (choice === "archive") await companionsApi.archive(character.id);
      else await companionsApi.remove(character.id);
      onDone(choice);
    } catch (e) {
      setError((e as Error).message || "That did not work. Try again.");
      setBusy(false);
    }
  };

  const option = (value: DeleteChoice, icon: React.ReactNode, title: string, body: string) => (
    <label
      className={cn(
        "flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors",
        choice === value
          ? value === "delete" ? "border-danger/60 bg-danger/5" : "border-primary bg-primary-50"
          : "border-border hover:bg-surface-mid",
      )}
    >
      <input
        type="radio"
        name="character-delete-choice"
        value={value}
        checked={choice === value}
        onChange={() => {
          setChoice(value);
          setError("");
        }}
        className="mt-1 accent-[var(--primary)]"
        disabled={busy}
      />
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
          {icon}
          {title}
        </span>
        <span className="mt-0.5 block text-xs text-ink-secondary">{body}</span>
      </span>
    </label>
  );

  return (
    <KbDialog
      open
      title={only ? `Delete ${character.name} permanently?` : `Delete ${character.name}?`}
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={BTN_SECONDARY} data-autofocus>
            Cancel
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={busy || !ready}
            className={choice === "delete" ? BTN_DANGER : BTN_PRIMARY}
          >
            {busy ? "Working…" : choice === "delete" ? "Delete permanently" : "Archive"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {!only &&
          option(
            "archive",
            <Archive size={15} aria-hidden="true" />,
            "Archive",
            "It stops answering and moves to the Archived tab. Chats and memory are kept, and you can restore it as Draft.",
          )}
        {only ? (
          <p className="text-sm text-ink-secondary">
            Its chats and everything it remembers about people are erased. Your collections and files stay. This can&apos;t be undone.
          </p>
        ) : (
          option(
            "delete",
            <Trash2 size={15} aria-hidden="true" />,
            "Delete permanently",
            "Erases it with its chats and everything it remembers about people. Your collections and files stay. This can't be undone.",
          )
        )}
        {needsName && (
          <div className="space-y-1.5 pt-1">
            <label htmlFor="confirm-character-name" className="block text-sm text-ink">
              {character.name} is Live on your site. Type <span className="font-semibold">{character.name}</span> to confirm.
            </label>
            <input
              id="confirm-character-name"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && confirm()}
              autoComplete="off"
              spellCheck={false}
              className={INPUT}
              disabled={busy}
            />
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </KbDialog>
  );
}
