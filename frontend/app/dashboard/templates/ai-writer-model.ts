/** "Previous prompts" for Write with AI: the last 5, newest first, in this browser only. */
const KEY = "templates:ai-prompts";
export const MAX_PROMPTS = 5;

export function addPrompt(list: string[], prompt: string): string[] {
  const p = prompt.trim();
  if (!p) return list;
  return [p, ...list.filter((x) => x !== p)].slice(0, MAX_PROMPTS);
}

export function readPrompts(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, MAX_PROMPTS) : [];
  } catch {
    return [];
  }
}

export function pushPrompt(prompt: string): string[] {
  const next = addPrompt(readPrompts(), prompt);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage blocked: the list just isn't remembered
  }
  return next;
}
