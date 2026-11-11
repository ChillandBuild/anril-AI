import type { ApiError } from "@/lib/api";

/**
 * Per-field messages from a FastAPI 422. Example: renaming Maya to an
 * 81-character name gives { name: "String should have at most 80 characters" }.
 * loc looks like ["body", "name"] or ["body", "sample_lines", 2]: the field is
 * the first string after "body".
 */
export function fieldErrors(detail: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!Array.isArray(detail)) return out;
  for (const item of detail) {
    if (!item || typeof item !== "object") continue;
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const field = loc.find((part, i) => typeof part === "string" && !(i === 0 && ["body", "query", "path"].includes(part)));
    if (typeof field !== "string" || out[field]) continue;
    out[field] = msg.replace(/^Value error, /, "");
  }
  return out;
}

/** What a failed character save should say. 409 is always the duplicate-name case. */
export function saveErrorMessage(err: unknown): { fields: Record<string, string>; message: string } {
  const e = err as ApiError;
  if (e?.status === 409) return { fields: { name: "Name already used" }, message: "" };
  if (e?.status === 422) {
    const fields = fieldErrors(e.detail);
    if (Object.keys(fields).length) return { fields, message: "Fix the highlighted fields." };
  }
  return { fields: {}, message: e?.message || "Could not save. Try again." };
}
