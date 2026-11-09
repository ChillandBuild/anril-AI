import type { ApiError, CompanionToolCall } from "@/lib/api";

/** How a tool call reads in the chat: get_chart({"dob":"1990-04-12"}), long args cut at 80 chars. */
export function formatToolCall(call: CompanionToolCall): string {
  const args = call.args && Object.keys(call.args).length ? JSON.stringify(call.args) : "";
  const shown = args.length > 80 ? `${args.slice(0, 79)}…` : args;
  return `${call.name}(${shown})`;
}

/** The owner types a tool's answer by hand: JSON if it parses as an object, else plain text. */
export function parseToolOutput(text: string): Record<string, unknown> | string {
  const trimmed = text.trim();
  if (trimmed.startsWith("{")) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
    } catch {
      /* not JSON: send as text */
    }
  }
  return trimmed;
}

/** "1.4 s" or "820 ms". */
export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/** The line shown when a test chat fails. 409 = paused character; 400 = no AI model set up. */
export function chatErrorText(err: unknown): string {
  const e = err as ApiError;
  return e?.message || "The character didn't answer. Try again.";
}

const TOOL_NAME = /^[a-z][a-z0-9_]{0,39}$/;
export function toolNameError(name: string, taken: string[]): string {
  if (!TOOL_NAME.test(name)) return "Use lowercase letters, numbers and _, starting with a letter (e.g. get_chart).";
  if (taken.includes(name)) return "That tool is already in the list.";
  return "";
}
