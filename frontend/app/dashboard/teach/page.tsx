"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { MessageCircle } from "lucide-react";
import { api, type TeachItem, type TeachOffer } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { AnswersCard } from "./AnswersCard";
import { OffersCard } from "./OffersCard";
import { WordsCard } from "./WordsCard";
import { LikedCard } from "./LikedCard";
import { MediaRuleCard } from "./MediaRuleCard";

export default function TeachPage() {
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const has = (p: string) => role === "owner" || permissions.includes(p);
  const canEdit = has("knowledge.manage");
  const canView = canEdit || has("knowledge.view") || has("brain.view");

  const [items, setItems] = useState<TeachItem[] | null>(null);
  const [offers, setOffers] = useState<TeachOffer[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const [i, o] = await Promise.all([api.aiTeach.items(), api.aiTeach.offers()]);
      setItems(i);
      setOffers(o);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  if (roleLoading) return <div className="m-6 min-h-[320px] animate-pulse rounded-2xl bg-border-subtle" />;
  if (!canView) {
    return (
      <div className="py-20 text-center">
        <p className="font-body text-sm text-ink-secondary">You do not have access to Teach &amp; offers.</p>
      </div>
    );
  }

  const answers = (items ?? []).filter((i) => i.kind === "answer");
  const words = (items ?? []).filter((i) => i.kind === "word");
  const liked = (items ?? []).filter((i) => i.kind === "liked");

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-6 sm:px-6">
      <div className="flex justify-end">
        <Link href="/dashboard/brain?section=test" className="btn-secondary min-h-9">
          <MessageCircle size={14} aria-hidden /> Test chat
        </Link>
      </div>

      {!canEdit && (
        <p className="rounded-xl bg-surface-low px-3 py-2 font-body text-sm text-ink-secondary">
          You can look at this, but only people with Knowledge Base access can change it.
        </p>
      )}

      {failed && (
        <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 font-body text-sm text-danger">
          Could not load this page.{" "}
          <button type="button" onClick={() => void load()} className="font-bold underline">Try again</button>
        </p>
      )}

      {items === null && offers === null && !failed ? (
        <div className="min-h-[240px] animate-pulse rounded-2xl bg-border-subtle" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[3fr_2fr] lg:items-start">
          <div className="space-y-4">
            <AnswersCard items={answers} canEdit={canEdit} onChange={() => void load()} />
            <WordsCard items={words} canEdit={canEdit} onChange={() => void load()} />
            <MediaRuleCard canEdit={canEdit} />
            <LikedCard items={liked} canEdit={canEdit} onChange={() => void load()} />
          </div>
          <OffersCard offers={offers ?? []} canEdit={canEdit} onChange={() => void load()} />
        </div>
      )}
    </div>
  );
}
