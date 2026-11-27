"use client";

import useSWR from "swr";
import { SectionCard } from "@/app/dashboard/otp/otpUi";
import { LoadError, Notice, Skeleton, TableWrap } from "@/app/dashboard/sms/ui";
import { connectionsApi, type AiReplies, type ChargesAvailable, type MetaCharges } from "@/lib/connectionsApi";
import { cn } from "@/lib/utils";
import {
  NOT_AVAILABLE_HELP,
  barTone,
  barWidth,
  formatCount,
  formatMoney,
  inShort,
} from "./chargesText";
import ReachLimitCard from "./ReachLimitCard";

const BAR_COLOR = { ok: "bg-primary", warn: "bg-amber-500", full: "bg-red-600" } as const;

export default function MetaChargesPage() {
  const { data, error, isLoading, mutate } = useSWR("connections:meta-charges", connectionsApi.metaCharges, {
    revalidateOnFocus: false,
  });

  return (
    <div className="w-full space-y-4">
      <ReachLimitCard />
      {error ? (
        <LoadError message={error instanceof Error ? error.message : "Something went wrong."} onRetry={() => mutate()} />
      ) : isLoading || !data ? (
        <LoadingState />
      ) : (
        <>
          <div>
            <p className="text-sm text-ink-secondary" data-testid="in-short">
              {inShort(data.charges, data.ai_replies)}
            </p>
          </div>

          <div className="min-w-0 space-y-4">
            <ChargesCard charges={data.charges} />
            <AiRepliesCard ai={data.ai_replies} />
          </div>
        </>
      )}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="w-full space-y-4" aria-busy="true">
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
            Meta counts by day (UTC), so this is approximately this month.
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
