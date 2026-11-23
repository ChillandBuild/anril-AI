"use client";

import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, CheckCircle2, Cloud, Smartphone } from "lucide-react";
import { SectionCard } from "@/app/dashboard/otp/otpUi";
import { Notice, Skeleton } from "@/app/dashboard/sms/ui";
import { connectionsApi, type CallingProvider } from "@/lib/connectionsApi";
import { cn } from "@/lib/utils";

const TEAM_LINK = "/dashboard/team";
const DO_NOT_CALL_LINK = "/dashboard/leads?tab=said-stop";
const COMING_LATER = [
  "Call recording settings",
  "Hide customer numbers",
  "Welcome menu (IVR)",
  "Missed call to WhatsApp",
  "Break limit",
];

const peopleText = (n: number) => `${n} ${n === 1 ? "person" : "people"}`;

function ModeTile({ icon: Icon, title, text, on, people }: { icon: typeof Cloud; title: string; text: string; on: boolean; people: number }) {
  return (
    <div className={cn("rounded-xl border p-4", on ? "border-primary/40 bg-primary/5" : "border-[#e2e8f0] bg-[#f8fafc]")}>
      <div className="flex items-center gap-2">
        <Icon size={18} className={on ? "text-primary" : "text-ink-secondary"} aria-hidden="true" />
        <p className="text-sm font-bold text-ink">{title}</p>
      </div>
      <p className="mt-1 text-sm text-ink-secondary">{text}</p>
      <p className={cn("mt-2 text-sm font-semibold", on ? "text-emerald-700" : "text-ink-secondary")}>
        {on ? `On · ${peopleText(people)}` : "Not on"}
      </p>
      {!on && <p className="mt-1 text-sm text-ink-secondary">Changing this is done by the Anril team with your plan.</p>}
    </div>
  );
}

function EditLink() {
  return (
    <Link href={TEAM_LINK} className="text-sm font-semibold text-primary hover:underline">
      Edit in Call IQ › Team
    </Link>
  );
}

export function CallingOverviewCard() {
  const { data, error, isLoading } = useSWR("connections:calling", connectionsApi.calling, { revalidateOnFocus: false });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (error || !data) {
    return <Notice tone="warn">{"Couldn't load the picture of how your team calls. The settings below still work."}</Notice>;
  }

  if (!data.available) {
    return (
      <Notice tone="warn">{"We couldn't read your calling setup right now, so we aren't showing it. The settings below still work."}</Notice>
    );
  }

  const provider: CallingProvider = data.provider;
  const people = data.people.length;

  return (
    <SectionCard title="How your team calls" description="What is switched on today. This part is read-only.">
      <div className="grid gap-3 sm:grid-cols-2">
        <ModeTile
          icon={Smartphone}
          title="SIM calling"
          text="Calls go out from each person's own phone."
          on={provider === "sim"}
          people={people}
        />
        <ModeTile
          icon={Cloud}
          title="Cloud calling"
          text="Calls go through a cloud phone line."
          on={provider === "cloud"}
          people={people}
        />
      </div>

      <h3 className="mt-5 text-sm font-bold text-ink">People</h3>
      {people === 0 ? (
        <p className="mt-2 text-sm text-ink-secondary">No one is set up to call yet. Add people in Call IQ › Team.</p>
      ) : (
        <ul className="mt-2 divide-y divide-[#f1f5f9] rounded-xl border border-[#e2e8f0]">
          {data.people.map((p, i) => (
            <li key={`${p.name}-${i}`} className="flex items-start gap-2 px-3 py-2.5">
              {p.ready ? (
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" aria-label="Ready" />
              ) : (
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" aria-label="Not ready" />
              )}
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">{p.name}</p>
                <p className="text-sm text-ink-secondary">{p.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-5 text-sm font-bold text-ink">Rules for the team</h3>
      <dl className="mt-2 divide-y divide-[#f1f5f9] rounded-xl border border-[#e2e8f0]">
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
          <div>
            <dt className="text-sm text-ink-secondary">Daily target</dt>
            <dd className="text-sm font-semibold text-ink">{data.rules.daily_target_calls} calls a day</dd>
          </div>
          <EditLink />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
          <div>
            <dt className="text-sm text-ink-secondary">Calling hours</dt>
            <dd className="text-sm font-semibold text-ink">{data.rules.calling_hours}</dd>
          </div>
          <EditLink />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
          <div>
            <dt className="text-sm text-ink-secondary">Do-not-call list</dt>
            <dd className="text-sm font-semibold text-ink">People a caller marked Don&apos;t call, in Customers › Said stop</dd>
          </div>
          <Link href={DO_NOT_CALL_LINK} className="text-sm font-semibold text-primary hover:underline">
            Open the list
          </Link>
        </div>
      </dl>

      <h3 className="mt-5 text-sm font-bold text-ink-secondary">Coming later</h3>
      <ul className="mt-2 grid gap-1.5 sm:grid-cols-2" aria-label="Coming later">
        {COMING_LATER.map((item) => (
          <li key={item} className="rounded-lg bg-[#f1f5f9] px-3 py-2 text-sm text-[#64748b]">
            {item}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
