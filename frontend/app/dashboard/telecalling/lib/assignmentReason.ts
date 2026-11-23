const REASON_LABEL: Record<string, string> = {
  created: "On entry", scored: "Scored up", manual: "Manual edit",
  sweep: "Sweep", bot_flow: "Bot flow", ai_agent: "AI agent",
  autopilot: "Autopilot", call_callback: "Call → callback", call_converted: "Call → won",
  caller_unavailable: "Caller away", backlog_claim: "Claimed on login",
  escalation: "Escalation", round_robin: "Round-robin",
};

/**
 * The plain-words reason shown in the Assignment Log. A lead moved because its telecaller went on leave reads
 * "Moved: Ravi on leave" (the person it was moved away from), or "Moved: on leave" when that name is gone.
 */
export function assignmentReasonLabel(reason: string | null | undefined, previousCallerName?: string | null): string {
  const key = reason || "";
  if (key === "moved_for_leave") {
    const name = (previousCallerName || "").trim();
    return name ? `Moved: ${name} on leave` : "Moved: on leave";
  }
  return REASON_LABEL[key] || reason || "—";
}
