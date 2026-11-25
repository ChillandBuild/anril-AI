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
import { isSmsOnly } from "@/lib/utils";
import { TodayBlock } from "./home/TodayBlock";
import { MoreDetails } from "./home/MoreDetails";
import { useHomeGate } from "./home/useHomeData";
import { FinishSetupCard } from "@/components/first-setup/FinishSetupCard";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useIsPhone } from "@/hooks/useIsPhone";

/** Phone only: today's date and a hello, above the "Needs you" card. Time of day is India time. */
function PhoneGreeting() {
  const { fullName } = useCurrentUser();
  const now = new Date();
  const hour = Number(now.toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const date = now.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  const first = fullName.split(" ")[0];
  return (
    <div className="px-1 lg:hidden">
      <p suppressHydrationWarning className="font-label text-[13px] font-bold text-ink-secondary">{date}</p>
      <p suppressHydrationWarning className="font-display text-2xl font-extrabold leading-tight text-ink">
        {part}
        {first ? `, ${first}` : ""}
      </p>
    </div>
  );
}

export function DashboardClient({ fallbackOverview }: { fallbackOverview: AnalyticsOverview | null }) {
  const { role, permissions, enabledFeatures, loading: roleLoading } = useAuthRole();
  const router = useRouter();
  const { status: subStatus } = useSubscription();
  // The greeting is phone-only and asks Supabase for the name: mount it only on a phone.
  const isPhone = useIsPhone();

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

  // SMS-only clients have nothing on this page; their home is the SMS dashboard. Pending or
  // unsubscribed tenants keep their subscription screen below.
  const smsHome =
    !roleLoading &&
    subStatus === "active" &&
    isSmsOnly(enabledFeatures) &&
    (role === "owner" || permissions.includes("sms.view") || permissions.includes("sms.manage"));
  useEffect(() => {
    if (smsHome) router.replace("/dashboard/sms");
  }, [smsHome, router]);

  // Home opens whole: the loader stays up until its own data is in (the rule is homeIsReady), so the lists,
  // numbers and cards appear together instead of one after another. Off for people being sent elsewhere.
  const telecalling = enabledFeatures.includes("telecalling");
  const showsHome =
    !roleLoading &&
    !smsHome &&
    !overviewError &&
    subStatus !== "none" &&
    subStatus !== "pending_approval" &&
    !(role === "caller" && !permissions.includes("dashboard.view"));
  const homeOpen = useHomeGate(showsHome, telecalling);

  if (roleLoading || smsHome) {
    return <AiraLoader />;
  }

  if (subStatus === "none" || subStatus === "pending_approval") {
    const isPending = subStatus === "pending_approval";
    return (
      <div className="animate-slide-up space-y-6">
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

  if (!overview || !homeOpen) {
    return <AiraLoader showRetryAfterMs={15000} onRetry={() => window.location.reload()} />;
  }

  return (
    <div className="dashboard-swiss space-y-5">
      {isPhone && <PhoneGreeting />}
      <FinishSetupCard />
      <TodayBlock />
      <MoreDetails overview={overview} telecalling={telecalling} />
    </div>
  );
}
