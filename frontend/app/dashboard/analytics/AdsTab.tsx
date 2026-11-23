"use client";

import { formatRupees, type AdRow, type AdsReport } from "@/lib/reportsApi";
import { PeriodMetrics } from "./PeriodMetrics";
import { ReportFrame } from "./ReportFrame";
import { DataTable, PeopleNumber, SectionCard, type Column } from "./reportsUi";

const LABELS: Record<string, string> = {
  spend_paise: "Spent on ads",
  chats: "Chats from ads",
  hot: "Hot chats from ads",
  sales: "Sales from ads",
  earned_paise: "Money earned",
  cost_per_chat_paise: "Cost per chat",
  cost_per_hot_paise: "Cost per hot chat",
  cost_per_sale_paise: "Cost per sale",
};

export function AdsTab({ query }: { query: string | null }) {
  return (
    <ReportFrame<AdsReport> tab="ads" query={query} csvTab="ads">
      {(data, tools) => {
        const showMoney = !data.money_hidden;
        const cols: Column<AdRow>[] = [
          { key: "name", label: "Ad", render: (r) => <span className="font-semibold">{r.name}</span> },
          { key: "platform", label: "Where", render: (r) => (r.platform === "google" ? "Google" : "Meta") },
          ...(showMoney ? [{ key: "spend", label: "Spent", right: true, render: (r: AdRow) => formatRupees(r.spend_paise) } as Column<AdRow>] : []),
          { key: "chats", label: "Chats", right: true, render: (r) => <PeopleNumber label={`${r.name} chats`} value={r.chats} onClick={() => tools.openPeople({ metric: "ad_chats", id: r.id }, `Chats from ${r.name}`)} /> },
          { key: "hot", label: "Hot", right: true, render: (r) => r.hot.toLocaleString("en-IN") },
          { key: "sales", label: "Sales", right: true, render: (r) => r.sales.toLocaleString("en-IN") },
          ...(showMoney
            ? ([
                { key: "earned", label: "Earned", right: true, render: (r: AdRow) => formatRupees(r.earned_paise) },
                { key: "cpc", label: "Per chat", right: true, render: (r: AdRow) => formatRupees(r.cost_per_chat_paise) },
                { key: "cph", label: "Per hot chat", right: true, render: (r: AdRow) => formatRupees(r.cost_per_hot_paise) },
                { key: "cps", label: "Per sale", right: true, render: (r: AdRow) => formatRupees(r.cost_per_sale_paise) },
                { key: "back", label: "Back per ₹1", right: true, render: (r: AdRow) => (r.money_back === null || r.money_back === undefined ? "—" : `₹${r.money_back.toFixed(2)}`) },
              ] as Column<AdRow>[])
            : []),
        ];
        return (
          <div className="space-y-5">
            <PeriodMetrics report={data} tools={tools} labels={LABELS} />
            <SectionCard title="Your ads" hint="Meta and Google together.">
              <DataTable columns={cols} rows={data.rows ?? []} rowKey={(r) => `${r.platform}-${r.id}`} empty="No ads ran in these days." />
            </SectionCard>
          </div>
        );
      }}
    </ReportFrame>
  );
}
