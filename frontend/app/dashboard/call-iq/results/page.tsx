"use client";

import { CallIqGate, CallIqPage } from "@/components/call-iq/CallIqShell";
import { ResultsBoard } from "@/components/call-iq/ResultsBoard";
import { canOpenTeamReports } from "@/lib/callIqApi";

export default function CallIqResultsPage() {
  return (
    <CallIqGate allow={canOpenTeamReports}>
      <CallIqPage title="Results" intro="Calls, then visits booked, then orders, then money, for each telecaller.">
        <ResultsBoard />
      </CallIqPage>
    </CallIqGate>
  );
}
