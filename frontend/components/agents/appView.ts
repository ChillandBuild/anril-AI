import type { CompanionReplyFormat } from "@/lib/api";

/**
 * Playground "App view": the reply comes back the way a client's app gets it from POST /chat
 * (bubbles, chips, one button, a tag), so the owner sees what the app's users see.
 * Example: appViewFormat("astrologer", 3) ->
 *   {buttons: [{id: "astrologer", when: "...", handoff: true}], questions_left: 3}
 */
const RESERVED = new Set(["counted", "ask_back", "greeting", "off_topic", "need_details", "none", "failed", "handoff"]);

/** A button id the API accepts: lowercase letters, digits and _, starting with a letter, up to 32. "" = not valid. */
export function cleanButtonId(raw: string): string {
  const id = raw.trim().toLowerCase().replace(/[\s-]+/g, "_").replace(/[^a-z0-9_]/g, "").slice(0, 32);
  return /^[a-z][a-z0-9_]*$/.test(id) && !RESERVED.has(id) ? id : "";
}

export function appViewFormat(buttonId: string, questionsLeft: number): CompanionReplyFormat {
  const id = cleanButtonId(buttonId);
  return {
    buttons: id ? [{ id, when: "the question needs a human expert from the business", handoff: true }] : [],
    questions_left: Math.max(0, Math.round(questionsLeft)),
  };
}

/** The app counts a question only on tag "counted": 3 -> 2. Never below 0. */
export function nextQuestionsLeft(left: number, tag: string | null | undefined): number {
  return tag === "counted" ? Math.max(0, left - 1) : left;
}

/** The grey line under an App view reply. Example: "questions left 3 → 2 · 2 bubbles · 2 chips · button". */
export function appViewLine(r: { bubbles: string[]; chips: string[]; button: string | null }, before: number, after: number): string {
  const parts = [`questions left ${before} → ${after}`, `${r.bubbles.length} bubble${r.bubbles.length === 1 ? "" : "s"}`];
  parts.push(r.chips.length ? `${r.chips.length} chips` : before === 0 ? "no chips (0 left)" : "no chips");
  if (r.button) parts.push("button");
  return parts.join(" · ");
}

const KEY = "anril.playground.appView";

export type AppViewPrefs = { on: boolean; button: string; left: number };
export const APP_VIEW_DEFAULTS: AppViewPrefs = { on: false, button: "expert", left: 3 };

/** Remembered per character, so Jothidar keeps "astrologer". A blocked or bad store gives the defaults. */
export function loadAppView(characterId: string): AppViewPrefs {
  try {
    const raw = JSON.parse(window.localStorage.getItem(`${KEY}.${characterId}`) ?? "null");
    if (!raw || typeof raw !== "object") return APP_VIEW_DEFAULTS;
    return {
      on: raw.on === true,
      button: typeof raw.button === "string" ? raw.button.slice(0, 32) : APP_VIEW_DEFAULTS.button,
      left: Number.isFinite(raw.left) ? Math.min(99, Math.max(0, Math.round(raw.left))) : APP_VIEW_DEFAULTS.left,
    };
  } catch {
    return APP_VIEW_DEFAULTS;
  }
}

export function saveAppView(characterId: string, prefs: AppViewPrefs): void {
  try {
    window.localStorage.setItem(`${KEY}.${characterId}`, JSON.stringify(prefs));
  } catch {
    /* private window: the switch still works, it just isn't remembered */
  }
}
