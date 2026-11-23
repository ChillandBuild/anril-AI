"use client";

import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, FileText, Gauge } from "lucide-react";
import { SectionCard } from "@/app/dashboard/otp/otpUi";
import { LoadError, Notice, Skeleton, TableWrap } from "@/app/dashboard/sms/ui";
import { connectionsApi, type AiReplies, type ChargesAvailable, type MetaCharges } from "@/lib/connectionsApi";
import { cn } from "@/lib/utils";
import {
  NOT_AVAILABLE_HELP,
  barTone,
  barWidth,
  dailyLimitText,
  formatCount,
  formatMoney,
  inShort,
} from "./chargesText";

const BAR_COLOR = { ok: "bg-primary", warn: "bg-amber-500", full: "bg-red-600" } as const;

export default function MetaChargesPage() {
  const { data, error, isLoading, mutate } = useSWR("connections:meta-charges", connectionsApi.metaCharges, {
    revalidateOnFocus: false,
  });

  if (error) {
    return (
      <LoadError message={error instanceof Error ? error.message : "Something went wrong."} onRetry={() => mutate()} />
    );
  }
  if (isLoading || !data) return <LoadingState />;

  return (
    <div className="w-full space-y-4">
      <div>
        <p className="text-sm text-ink-secondary" data-testid="in-short">
          {inShort(data.charges, data.ai_replies)}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <ChargesCard charges={data.charges} />
          <AiRepliesCard ai={data.ai_replies} />
        </div>
        <MovedCard tier={data.daily_limit.tier} numbersLink={data.daily_limit.link} />
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="w-full space-y-4" aria-busy="true">
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function ChargesCard({ charges }: { charges: MetaCharges }) {
  return (
    <SectionCard title="Meta's charges this month" description="These are Meta's own numbers for this calendar month. Meta adds GST on top.">
      {charges.available ? (
        <>
          <ChargesTable charges={charges} />
          <p className="mt-3 text-sm text-ink-secondary">
            Meta counts by UTC day, so this is approximately this month.
          </p>
        </>
      ) : (
        <Notice tone="warn">
          <p className="font-semibold">{charges.reason}</p>
          <p className="mt-1">{NOT_AVAILABLE_HELP}</p>
        </Notice>
      )}
    </SectionCard>
  );
}

function ChargesTable({ charges }: { charges: ChargesAvailable }) {
  const th = "px-3 py-2 text-left text-xs font-semibold text-ink-secondary";
  return (
    <TableWrap>
      <table className="w-full min-w-[320px] text-sm">
        <thead>
          <tr className="border-b border-[#e2e8f0]">
            <th className={th}>Messages</th>
            <th className={cn(th, "text-right")}>Charge</th>
          </tr>
        </thead>
        <tbody>
          {charges.rows.map((row) => (
            <tr key={row.key} className="border-b border-[#f1f5f9]">
              <td className="px-3 py-3 text-sm text-[#334155]">
                <p className="font-semibold text-ink">{row.label}</p>
                <p className="text-xs text-ink-secondary">{formatCount(row.messages)} sent</p>
              </td>
              <td className="px-3 py-3 text-right text-sm tabular-nums text-ink">
                {row.key === "service" && row.cost === 0 ? "Free" : formatMoney(row.cost, charges.currency)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td className="px-3 py-3 text-sm font-bold text-ink">Total</td>
            <td className="px-3 py-3 text-right text-sm font-bold tabular-nums text-ink">
              {formatMoney(charges.total.cost, charges.currency)} {charges.gst_note}
            </td>
          </tr>
        </tfoot>
      </table>
    </TableWrap>
  );
}

function AiRepliesCard({ ai }: { ai: AiReplies }) {
  const tone = barTone(ai.pct);
  return (
    <SectionCard title="AI replies used" description="Replies the AI wrote for your customers in this plan period.">
      {ai.included != null && ai.pct != null ? (
        <>
          <p className="text-sm text-ink">
            <span className="font-bold tabular-nums">{formatCount(ai.used)}</span> of{" "}
            <span className="tabular-nums">{formatCount(ai.included)}</span> used ({ai.pct}%)
          </p>
          <div
            className="mt-3 h-3 w-full overflow-hidden rounded-full bg-[#eef2f6]"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={barWidth(ai.pct)}
            aria-label="AI replies used"
          >
            <div className={cn("h-full rounded-full", BAR_COLOR[tone])} style={{ width: `${barWidth(ai.pct)}%` }} />
          </div>
          {tone !== "ok" && (
            <p className="mt-2 text-sm text-ink-secondary">
              {tone === "full" ? "You have used all your AI replies for this period." : "You are close to your AI reply limit."}
            </p>
          )}
        </>
      ) : (
        <p className="text-sm text-ink">
          <span className="font-bold tabular-nums">{formatCount(ai.used)}</span> used this period. Your plan has no set
          AI reply allowance.
        </p>
      )}
    </SectionCard>
  );
}

function MovedCard({ tier, numbersLink }: { tier: number | null; numbersLink: string }) {
  return (
    <SectionCard title="Moved out of this page" description="These used to be mixed in here. They have their own pages now.">
      <ul className="space-y-4">
        <li className="flex items-start gap-3">
          <Gauge size={18} className="mt-0.5 shrink-0 text-ink-secondary" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">Daily sending limit</p>
            <p className="text-sm text-ink-secondary">{dailyLimitText(tier)}</p>
            <Link href={numbersLink} className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
              WhatsApp › Numbers <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
        </li>
        <li className="flex items-start gap-3">
          <FileText size={18} className="mt-0.5 shrink-0 text-ink-secondary" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">Template status</p>
            <p className="text-sm text-ink-secondary">See which message templates Meta has approved.</p>
            <Link href="/dashboard/templates" className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
              Templates <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
        </li>
      </ul>
    </SectionCard>
  );
}
