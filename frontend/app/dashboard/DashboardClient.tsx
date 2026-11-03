"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AnalyticsOverview } from "@/lib/api";
import { useOverview } from "@/hooks/useApi";
import {
  Sparkles,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import Link from "next/link";
import { useAuthRole } from "./contexts/AuthRoleContext";
import { useSubscription } from "./contexts/SubscriptionContext";
import { AiraLoader } from "@/components/AiraLoader";
import { PipelinePulse } from "@/components/dashboard/PipelinePulse";
import { AiWorkloadSection } from "@/components/dashboard/AiWorkloadSection";
import { LeadSourceSection } from "@/components/dashboard/LeadSourceSection";
import { TeamCallsSection } from "@/components/dashboard/TeamCallsSection";
import { AdSpendSection } from "@/components/dashboard/AdSpendSection";
import { isSmsOnly } from "@/lib/utils";

const SEGMENT_CONFIG: Record<"A" | "B" | "C" | "D", { label: string; tone: string; bar: string; bg: string; borderTop: string }> = {
  A: { label: "Hot", tone: "text-emerald-700", bar: "bg-emerald-500", bg: "bg-emerald-50", borderTop: "border-t-emerald-500" },
  B: { label: "Warm", tone: "text-amber-700", bar: "bg-amber-500", bg: "bg-amber-50", borderTop: "border-t-amber-500" },
  C: { label: "Cold", tone: "text-ink-muted", bar: "bg-stone-400", bg: "bg-stone-100", borderTop: "border-t-stone-400" },
  D: { label: "Not Interested", tone: "text-rose-600", bar: "bg-rose-400", bg: "bg-rose-50", borderTop: "border-t-rose-500" },
};

function PipelineBar({ by_segment }: { by_segment: Record<"A" | "B" | "C" | "D", number> }) {
  const counts = (["A", "B", "C", "D"] as const).map((s) => ({
    seg: s,
    count: by_segment?.[s] ?? 0,
  }));
  const total = counts.reduce((acc, c) => acc + c.count, 0);
  // Matches the backend's UTC calendar day used to build by_segment_today,
  // so the leads list this links to shows exactly what the card counted.
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="card rounded-xl p-6 md:p-7">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="font-display font-bold text-ink text-[18px]">
            Pipeline Activity
          </h2>
          <p className="font-body text-xs text-ink-muted mt-1">
            {total === 0 ? "No leads yet today" : `${total} leads categorized today`}
          </p>
        </div>
      </div>

      {total === 0 ? (
        <div className="py-8 text-center font-body text-sm text-ink-muted">
          No new leads today yet.
        </div>
      ) : (
        <>
          {/* Stacked bar chart */}
          <div className="h-3 rounded-full overflow-hidden flex bg-surface-mid mb-6">
            {counts.map(({ seg, count }) =>
              count > 0 ? (
                <div
                  key={seg}
                  className={SEGMENT_CONFIG[seg].bar}
                  style={{ width: `${(count / total) * 100}%` }}
                  title={`${SEGMENT_CONFIG[seg].label}: ${count}`}
                />
              ) : null,
            )}
          </div>

          {/* Table list */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {counts.map(({ seg, count }) => {
              const cfg = SEGMENT_CONFIG[seg];
              const pct = total ? Math.round((count / total) * 100) : 0;
              return (
                <Link
                  key={seg}
                  href={`/dashboard/leads?segment=${seg}&date_from=${today}&date_to=${today}`}
                  className={`p-4 rounded-2xl ${cfg.bg} border border-border/40 border-t-4 ${cfg.borderTop} hover:border-border transition-all`}
                >
                  <div className="font-mono font-bold text-ink text-[22px]">
                    {count}
                  </div>
                  <div className="font-label text-[10px] font-semibold mt-1 uppercase tracking-wider text-ink-secondary">
                    {cfg.label}
                  </div>
                  <div className="font-body text-[11px] text-ink-muted mt-0.5">{pct}% of today&apos;s leads</div>
                </Link>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

export function DashboardClient({ fallbackOverview }: { fallbackOverview: AnalyticsOverview | null }) {
  const { role, permissions, enabledFeatures, loading: roleLoading } = useAuthRole();
  const router = useRouter();
  const { status: subStatus } = useSubscription();

  // Seeded from the server for owners (instant paint); callers get null and are
  // redirected below. Enable the SWR key when role confirms owner OR we already
  // have server-seeded data (server only returns 200 to owners).
  const { data: overview, error: overviewError } = useOverview(
    role === "owner" || permissions.includes("dashboard.view") || fallbackOverview !== null,
    fallbackOverview ?? undefined,
  );

  // Redirect users without dashboard permission to their profile page.
  useEffect(() => {
    if (!roleLoading && role === "caller" && !permissions.includes("dashboard.view")) {
      router.replace("/dashboard/profile");
    }
  }, [permissions, role, roleLoading, router]);

  // SMS-only clients have nothing on this page; their home is the SMS dashboard.
  const smsHome =
    !roleLoading &&
    isSmsOnly(enabledFeatures) &&
    (role === "owner" || permissions.includes("sms.view") || permissions.includes("sms.manage"));
  useEffect(() => {
    if (smsHome) router.replace("/dashboard/sms");
  }, [smsHome, router]);

  if (roleLoading || smsHome) {
    return <AiraLoader />;
  }

  if (subStatus === "none" || subStatus === "pending_approval") {
    const isPending = subStatus === "pending_approval";
    return (
      <div className="animate-slide-up space-y-6 max-w-4xl">
        <div className="card rounded-xl p-6 md:p-7 border border-border bg-gradient-to-br from-primary-light to-white shadow-sm">
          <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Sparkles size={24} />
          </div>
          <h1 className="font-display text-3xl font-bold text-ink mb-2">Welcome to Anril AI</h1>
          <p className="text-sm text-ink-muted leading-relaxed max-w-2xl">
            You have successfully set up your workspace credentials! To begin engaging leads with intelligent telecalling campaigns, custom WhatsApp automation, and live chat, please configure your subscription.
          </p>

          <div className="mt-8 rounded-2xl bg-white border border-border/80 p-6 max-w-2xl">
            <h2 className="font-display text-lg font-bold text-ink mb-1.5">
              {isPending ? "Awaiting admin activation" : "Setup your subscription plan"}
            </h2>
            <p className="text-xs text-ink-muted mb-6 leading-relaxed">
              {isPending
                ? "Your subscription request has been submitted to the platform operator. Once payment is confirmed, your workspace will be fully unlocked."
                : "Select from our ready-made quick-start packages or build a custom configuration of channels, seats, and numbers matching your scale."}
            </p>
            <Link
              href="/dashboard/subscription"
              className="btn-primary inline-flex items-center gap-2 text-sm font-semibold transition-all duration-200"
            >
              <span>{isPending ? "View Subscription Status" : "Configure Subscription"}</span>
              <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (role === "caller" && !permissions.includes("dashboard.view")) {
    return <AiraLoader />;
  }

  if (overviewError) {
    const status = (overviewError as { status?: number }).status;
    const message =
      status === 403
        ? "This role can open the dashboard, but the analytics overview is not allowed yet. Ask an admin to add Dashboard access or Analytics access."
        : overviewError instanceof Error
          ? overviewError.message
          : "Dashboard analytics could not be loaded.";
    return (
      <div className="flex min-h-[55vh] items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-3xl border border-red-100 bg-white p-6 text-center shadow-sm">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-red-50 text-red-600">
            <AlertCircle size={20} />
          </div>
          <p className="mt-4 font-label text-[10px] font-black uppercase tracking-wider text-red-600">
            Dashboard data unavailable
          </p>
          <p className="mt-3 font-body text-sm leading-6 text-ink-muted">{message}</p>
          <button type="button" onClick={() => window.location.reload()} className="btn-primary mt-5 justify-center">
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!overview) {
    return <AiraLoader showRetryAfterMs={15000} onRetry={() => window.location.reload()} />;
  }

  return (
    <div className="dashboard-swiss space-y-8">
      <PipelinePulse overview={overview} />

      <AiWorkloadSection overview={overview} />

      <PipelineBar by_segment={overview.by_segment_today ?? { A: 0, B: 0, C: 0, D: 0 }} />

      <LeadSourceSection overview={overview} />

      {enabledFeatures.includes("telecalling") && <TeamCallsSection />}

      <AdSpendSection />
    </div>
  );
}
