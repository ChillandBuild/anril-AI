"use client";

import { useEffect, useState } from "react";
import { Loader2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { SwitchPill } from "@/components/ui/controls";
import { setAiAgentOn } from "@/lib/firstSetupApi";
import { knowledgeWebApi, undoQuestion, type UndoPreview } from "@/lib/knowledgeWebApi";

/**
 * v9.2 #168 Brain page header: the AI on/off switch (the same setting as Settings > Auto-reply) and
 * "Undo last change" (shown only when the Knowledge Base has a change to put back).
 */
export function BrainHeaderControls({
  aiOn,
  canSwitch,
  canUndo,
  onChanged,
}: {
  aiOn: boolean;
  canSwitch: boolean;
  canUndo: boolean;
  onChanged: () => void;
}) {
  const [on, setOn] = useState(aiOn);
  const [switching, setSwitching] = useState(false);
  const [undo, setUndo] = useState<UndoPreview>({ available: false });
  const [undoing, setUndoing] = useState(false);

  useEffect(() => setOn(aiOn), [aiOn]);

  useEffect(() => {
    if (!canUndo) return;
    let live = true;
    knowledgeWebApi.undoPreview().then((p) => live && setUndo(p)).catch(() => live && setUndo({ available: false }));
    return () => {
      live = false;
    };
  }, [canUndo]);

  async function flip(next: boolean) {
    if (switching) return;
    setSwitching(true);
    setOn(next);
    try {
      await setAiAgentOn(next);
      toast.success(next ? "AI is on." : "AI is off. Customers will wait for your team.");
      onChanged();
    } catch (err) {
      setOn(!next);
      toast.error(err instanceof Error ? err.message : "Couldn't change the AI switch.");
    } finally {
      setSwitching(false);
    }
  }

  async function undoLast() {
    if (!undo.available || undoing) return;
    if (!confirm(undoQuestion(undo))) return;
    setUndoing(true);
    try {
      await knowledgeWebApi.undo(undo.version_id);
      toast.success("Put back the earlier version.");
      onChanged();
      knowledgeWebApi.undoPreview().then(setUndo).catch(() => setUndo({ available: false }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't undo the last change.");
    } finally {
      setUndoing(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {canUndo && undo.available && (
        <button
          type="button"
          onClick={() => void undoLast()}
          disabled={undoing}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border bg-white px-3 font-label text-xs font-bold text-ink hover:bg-surface-mid focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
        >
          {undoing ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <Undo2 size={13} aria-hidden />}
          Undo last change
        </button>
      )}
      <label className="inline-flex min-h-10 items-center gap-2 font-label text-xs font-bold text-ink">
        AI {on ? "on" : "off"}
        <SwitchPill on={on} onChange={(next) => void flip(next)} disabled={!canSwitch} loading={switching} size="sm" aria-label="AI replies on or off" />
      </label>
    </div>
  );
}
