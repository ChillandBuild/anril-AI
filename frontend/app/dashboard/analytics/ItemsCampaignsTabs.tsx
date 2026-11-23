"use client";

import Link from "next/link";
import { formatRupees, type CampaignRow, type CampaignsReport, type ItemsReport } from "@/lib/reportsApi";
import { PeriodMetrics } from "./PeriodMetrics";
import { ReportFrame } from "./ReportFrame";
import { DataTable, PeopleNumber, SectionCard, type Column } from "./reportsUi";

export function ItemsTab({ query }: { query: string | null }) {
  return (
    <ReportFrame<ItemsReport> tab="items" query={query} csvTab="items">
      {(data, tools) => (
        <div className="space-y-5">
          <PeriodMetrics report={data} tools={tools} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:gap-6">
            <SectionCard title="Best sellers">
              <DataTable
                rows={data.top_items ?? []}
                rowKey={(r) => r.name}
                empty="No items sold in these days."
                columns={[
                  { key: "name", label: "Item", render: (r) => <span className="font-semibold">{r.name}</span> },
                  { key: "qty", label: "Sold", right: true, render: (r) => r.qty.toLocaleString("en-IN") },
                  ...(data.money_hidden ? [] : [{ key: "paise", label: "Sales", right: true, render: (r: { sales_paise?: number | null }) => formatRupees(r.sales_paise) }]),
                ]}
              />
            </SectionCard>
            <SectionCard title="Running low" hint="Items to buy again soon.">
              <DataTable
                rows={data.low_stock ?? []}
                rowKey={(r) => r.name}
                empty="Nothing is running low."
                columns={[
                  { key: "name", label: "Item", render: (r) => <Link href="/dashboard/catalog" className="font-semibold text-primary underline-offset-2 hover:underline">{r.name}</Link> },
                  { key: "left", label: "Left", right: true, render: (r) => r.left.toLocaleString("en-IN") },
                ]}
              />
            </SectionCard>
          </div>
          <SectionCard title="Orders by step">
            <DataTable
              rows={data.orders_by_stage ?? []}
              rowKey={(r) => r.stage}
              empty="No orders in these days."
              columns={[
                { key: "stage", label: "Step", render: (r) => <span className="font-semibold">{r.label || r.stage}</span> },
                { key: "count", label: "Orders", right: true, render: (r) => r.count.toLocaleString("en-IN") },
                ...(data.money_hidden ? [] : [{ key: "paise", label: "Amount", right: true, render: (r: { total_paise?: number | null }) => formatRupees(r.total_paise) }]),
              ]}
            />
          </SectionCard>
        </div>
      )}
    </ReportFrame>
  );
}

const N = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("en-IN"));

export function CampaignsTab({ query }: { query: string | null }) {
  return (
    <ReportFrame<CampaignsReport> tab="campaigns" query={query} csvTab="campaigns">
      {(data, tools) => {
        const cols: Column<CampaignRow>[] = [
          { key: "name", label: "Campaign", render: (r) => <span className="font-semibold">{r.name}</span> },
          { key: "sent", label: "Sent", right: true, render: (r) => N(r.sent) },
          { key: "delivered", label: "Delivered", right: true, render: (r) => N(r.delivered) },
          { key: "read", label: "Read", right: true, render: (r) => N(r.read) },
          { key: "replied", label: "Replied", right: true, render: (r) => <PeopleNumber label={`${r.name} replied`} value={r.replied} onClick={() => tools.openPeople({ metric: "campaign_replied", id: r.id }, `Replied to ${r.name}`)} /> },
          { key: "stop", label: "Said stop", right: true, render: (r) => N(r.said_stop) },
          { key: "paid", label: "Paid in 7 days", right: true, render: (r) => <PeopleNumber label={`${r.name} paid`} value={r.paid} onClick={() => tools.openPeople({ metric: "campaign_paid", id: r.id }, `Paid after ${r.name}`)} /> },
          ...(data.money_hidden ? [] : [{ key: "paise", label: "Money", right: true, render: (r: CampaignRow) => formatRupees(r.paid_paise) } as Column<CampaignRow>]),
        ];
        return (
          <div className="space-y-5">
            <PeriodMetrics report={data} tools={tools} />
            <SectionCard title="Your campaigns" hint="Messages you sent to groups of people.">
              <DataTable columns={cols} rows={data.rows ?? []} rowKey={(r) => r.id} empty="No campaigns went out in these days." />
            </SectionCard>
          </div>
        );
      }}
    </ReportFrame>
  );
}
