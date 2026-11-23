"use client";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { likedMarks } from "@/components/ai-setup/likedMarks";

/** A 👍 on one AI reply: saves it as a style example for the AI agent. Only owners and Knowledge Base editors see it. */
export function LikeReply({ messageId }: { messageId: string }) {
  const { role, permissions } = useAuthRole();
  const canLike = role === "owner" || permissions.includes("knowledge.manage");
  const [liked, setLiked] = useState(false);
  const [busy, setBusy] = useState(false);

  // A reply liked earlier (before a reload) shows as liked. One call covers every reply on screen.
  useEffect(() => {
    if (!canLike) return;
    let alive = true;
    void likedMarks.get(messageId).then((value) => {
      if (alive) setLiked(value);
    });
    return () => { alive = false; };
  }, [messageId, canLike]);

  async function like() {
    if (busy) return;
    setBusy(true);
    try {
      await api.aiTeach.like(messageId);
      likedMarks.set(messageId, true);
      setLiked(true);
      toast.success("Saved. The AI agent will copy this style.");
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
      await api.aiTeach.unlike(messageId);
      likedMarks.set(messageId, false);
      setLiked(false);
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Could not undo that. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!canLike) return null;

  if (liked) {
    return (
      <p className="mt-1 font-body text-xs font-semibold text-primary">
        {"👍 Liked · saved for the AI agent"}{" "}
        <button type="button" onClick={undo} disabled={busy} className="font-semibold text-primary underline">Undo</button>
      </p>
    );
  }

  return (
    <button type="button" onClick={like} disabled={busy}
      className="mt-1 inline-flex min-h-7 items-center rounded-md px-1.5 text-xs text-[#556274] hover:bg-white/70 hover:text-[#0A1528] disabled:opacity-50">
      <span aria-hidden>{"👍"}</span><span className="ml-1 font-label font-semibold">Like this reply</span>
    </button>
  );
}
