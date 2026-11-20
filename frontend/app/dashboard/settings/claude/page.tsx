"use client";
import { ClaudeConnectorPanel } from "../ClaudeConnectorPanel";

// Settings → Anril AI for Claude. The backend decides who may see what (owner only, and only a
// client the operator switched on); the panel shows its answer.
export default function ClaudeSettingsPage() {
  return <ClaudeConnectorPanel />;
}
