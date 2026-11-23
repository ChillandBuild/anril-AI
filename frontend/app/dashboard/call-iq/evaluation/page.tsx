"use client";

import { CallIqGate, CallIqPage } from "@/components/call-iq/CallIqShell";
import { EvaluationBoard } from "@/components/call-iq/EvaluationBoard";
import { canOpenTeamReports } from "@/lib/callIqApi";

export default function CallIqEvaluationPage() {
  return (
    <CallIqGate allow={canOpenTeamReports}>
      <CallIqPage title="Evaluation" intro="How well each telecaller talks to customers, scored by the AI, and where each one can improve.">
        <EvaluationBoard />
      </CallIqPage>
    </CallIqGate>
  );
}
