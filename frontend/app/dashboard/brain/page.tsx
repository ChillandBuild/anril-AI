"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import KnowledgeReviewModal from "@/app/dashboard/knowledge/KnowledgeReviewModal";
import { announceApprovalsChanged } from "@/components/brain/approvalsEvent";
import { BrainWorkspace } from "@/components/brain/BrainWorkspace";
import { HandoverFeed } from "@/components/brain/HandoverFeed";
import { HeadlineStrip } from "@/components/brain/HeadlineStrip";
import { NextBrainAction } from "@/components/brain/NextBrainAction";
import { InputsList } from "@/components/brain/InputsList";
import { TestAira } from "@/components/brain/TestAira";
import { NEEDS_MANAGE_REASON } from "@/components/brain/testAiraLogic";
import { useBrainData } from "@/components/brain/useBrainData";
import { WaitingOnYou } from "@/components/brain/WaitingOnYou";
import { AiraLoader } from "@/components/AiraLoader";

const TEST_AIRA_ENDPOINT = "/api/v1/brain/sandbox";

function LoadingState() {
  return <AiraLoader inline />;
}

function ErrorState({ message, isRetrying, onRetry }: { message: string; isRetrying: boolean; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50/60 p-4 sm:p-5">
      <div className="flex min-w-0 items-start gap-2.5">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
        <p className="min-w-0 break-words font-body text-sm text-ink">{message}</p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        className="inline-flex min-h-9 items-center rounded-lg border border-border bg-white px-3 font-label text-xs font-bold text-ink hover:border-primary/40 disabled:opacity-50"
      >
        {isRetrying && <Loader2 size={12} className="mr-1.5 animate-spin" aria-hidden />}
        Try again
      </button>
    </div>
  );
}

export default function AiraBrainPage() {
  const { role, permissions, loading: roleLoading } = useAuthRole();
  const searchParams = useSearchParams();
  const router = useRouter();
  const testQuestion = (searchParams.get("question") ?? "").slice(0, 2000);
  const requestedSection = searchParams.get("section");
  const canView = role === "owner" || permissions.includes("brain.view");
  const canManage = role === "owner" || permissions.includes("knowledge.manage");
  const isOwner = role === "owner";

  const { data, error, isLoading, isRetrying, panelKey, refreshedAt, refreshError, retry } = useBrainData(canView);
  const [reviewingDocumentId, setReviewingDocumentId] = useState<string | null>(null);

  const [activeSection, setActiveSection] = useState("overview");
  const [pendingAnchor, setPendingAnchor] = useState<string | null>(null);

  useEffect(() => {
    if (requestedSection && ["overview", "approvals", "knowledge", "handovers", "test"].includes(requestedSection)) setActiveSection(requestedSection);
  }, [requestedSection]);

  function addAnswer(question: string) {
    router.push(`/dashboard/knowledge?${new URLSearchParams({ tab: "documents", question })}`);
  }

  function openAnchor(anchor: string) {
    setActiveSection("approvals");
    setPendingAnchor(anchor);
  }

  useEffect(() => {
    function followHash() {
      const anchor = window.location.hash.slice(1);
      if (["brain-conflicts", "brain-failed-files", "brain-templates"].includes(anchor)) openAnchor(anchor);
    }
    followHash();
    window.addEventListener("hashchange", followHash);
    return () => window.removeEventListener("hashchange", followHash);
  }, []);

  useEffect(() => {
    if (!pendingAnchor || !data) return;
    document.getElementById(pendingAnchor)?.scrollIntoView({ block: "nearest" });
    setPendingAnchor(null);
  }, [pendingAnchor, data]);

  function openReview(reviewId: string): void {
    const review = data?.waiting.sort_reviews.find((r) => r.id === reviewId);
    if (review) setReviewingDocumentId(review.document_id);
  }

  // The modal's handlers only announce; the hub and the sidebar badge both listen
  // for the event, so there is one path from "approved" to "reloaded".
  function closeReview(): void {
    setReviewingDocumentId(null);
    announceApprovalsChanged();
  }

  if (roleLoading) return <LoadingState />;

  if (!canView) {
    return (
      <div className="mx-auto max-w-3xl rounded-2xl border border-border bg-white p-5">
        <p className="font-body text-sm text-ink-secondary">You don&apos;t have access to Anril Brain.</p>
      </div>
    );
  }

  return (
    <>
      <div className="mx-auto flex min-w-0 max-w-6xl flex-col gap-5">
        {isLoading && <LoadingState />}
        {!isLoading && error && data === null && <ErrorState message={error} isRetrying={isRetrying} onRetry={retry} />}
        {data && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="font-body text-xs text-ink-secondary">
                {refreshedAt ? <>Status loaded at <time dateTime={refreshedAt}>{new Date(refreshedAt).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" })} IST</time></> : "Loading current status…"}
                {" · Conflict check time is shown under Needs attention."}
              </p>
              <button type="button" disabled={isRetrying} onClick={retry} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border bg-white px-3 font-label text-xs font-bold text-ink hover:bg-surface-mid focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50">
                <RefreshCw size={13} aria-hidden className={isRetrying ? "animate-spin" : ""} />Refresh status
              </button>
            </div>
            {refreshError && <p role="alert" className="font-body text-sm text-danger">{refreshError} Showing the last loaded status; try refreshing again.</p>}
            <NextBrainAction brain={data} onSelect={setActiveSection} activeSection={activeSection} canManageSettings={isOwner || permissions.includes("settings.manage")} />
            <BrainWorkspace activeId={activeSection} onSelect={setActiveSection} sections={[
              { id: "overview", label: "Overview", description: "How Anril is doing and where its answers can improve.", content: <HeadlineStrip headline={data.headline} /> },
              { id: "approvals", label: "Needs attention", description: "Review sorted files, resolve conflicts, and fix failed inputs.", count: data.waiting.count, content: <WaitingOnYou waiting={data.waiting} canManage={canManage} isOwner={isOwner} panelKey={panelKey} onConflictsChanged={announceApprovalsChanged} onOpenReview={openReview} onTest={() => setActiveSection("test")} /> },
              { id: "knowledge", label: "What Anril knows", description: "Check the information Anril reads before answering.", content: <InputsList inputs={data.inputs} /> },
              { id: "handovers", label: "Handovers", description: "See which conversations needed a person.", content: <HandoverFeed handovers={data.handovers} canManageKnowledge={canManage} /> },
              { id: "test", scrollable: false, label: "Test Anril", description: "Try a customer message and inspect Anril’s response.", content: <TestAira endpoint={TEST_AIRA_ENDPOINT} canUse={canManage} disabledReason={NEEDS_MANAGE_REASON} initialQuestion={testQuestion} onAddAnswer={canManage ? addAnswer : undefined} /> },
            ]} />
          </>
        )}
      </div>

      {/* Outside the flex column on purpose: a fixed overlay inside a gap/space container gets pushed off the top edge. */}
      {reviewingDocumentId && (
        <KnowledgeReviewModal
          documentId={reviewingDocumentId}
          canManage={canManage}
          isOwner={isOwner}
          onClose={() => setReviewingDocumentId(null)}
          onFinished={closeReview}
          onResorted={closeReview}
        />
      )}
    </>
  );
}
