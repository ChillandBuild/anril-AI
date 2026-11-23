"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  downloadCsv, getReport, type CsvTab, type PeopleRef, type ReportBase, type ReportTab,
} from "@/lib/reportsApi";
import {
  Empty, ErrorBox, InShort, Loading, PeopleSheet, PlainNote, ReportActions, usePeopleSheet, useReport,
} from "./reportsUi";

export interface FrameTools {
  openPeople: (ref: PeopleRef, title: string) => void;
}

/**
 * What every data tab shares: load, the "In short" line, refresh / download / print,
 * the people side sheet, and the notice when the server hides rupee figures.
 */
export function ReportFrame<T extends ReportBase>({
  tab, query, csvTab, onMoneyHidden, children,
}: {
  tab: Exclude<ReportTab, "ask">;
  /** null while a custom range is not complete. */
  query: string | null;
  csvTab?: CsvTab;
  onMoneyHidden?: (hidden: boolean) => void;
  children: (data: T, tools: FrameTools) => ReactNode;
}) {
  const { data, err, loading, reload } = useReport<T>(query, (q) => getReport<T>(tab, q));
  const sheet = usePeopleSheet();
  const [downloadErr, setDownloadErr] = useState<string | null>(null);

  useEffect(() => {
    if (data && onMoneyHidden) onMoneyHidden(!!data.money_hidden);
  }, [data, onMoneyHidden]);

  if (!query) return <Empty>Pick a start and an end date to see this report.</Empty>;

  const onDownload = csvTab
    ? () => {
        setDownloadErr(null);
        downloadCsv(csvTab, query).catch((e: unknown) => setDownloadErr(e instanceof Error ? e.message : "The download did not work."));
      }
    : undefined;

  return (
    <div className="space-y-5">
      <ReportActions onReload={reload} onDownload={onDownload} downloadLabel="Download (CSV)" busy={loading} />
      {downloadErr && <ErrorBox message={downloadErr} />}
      {err && <ErrorBox message={err} onRetry={reload} />}
      {loading && <Loading />}
      {data && (
        <>
          <InShort text={data.in_short} />
          {data.money_hidden && <PlainNote>Money figures are hidden for your login. Ask the owner if you need to see them.</PlainNote>}
          {children(data, { openPeople: sheet.open })}
        </>
      )}
      <PeopleSheet request={sheet.request} query={query} onClose={sheet.close} />
    </div>
  );
}
