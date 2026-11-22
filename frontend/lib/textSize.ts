/**
 * Text size and Darker text: a per-person, per-device choice kept in localStorage and applied as
 * data attributes on <html> (data-text-size, data-darker-text). globals.css does the rest.
 * Every storage touch is wrapped in try/catch: private windows and blocked storage fall back to normal.
 */

export type TextSize = "normal" | "big" | "bigger";

export const TEXT_SIZE_KEY = "anril.textSize";
export const DARKER_TEXT_KEY = "anril.darkerText";
export const TEXT_SIZES: readonly TextSize[] = ["normal", "big", "bigger"];

/** Anything that is not one of the three known sizes is "normal". */
export function parseTextSize(value: unknown): TextSize {
  return value === "big" || value === "bigger" ? value : "normal";
}

/** Only "1" turns Darker text on. */
export function parseDarkerText(value: unknown): boolean {
  return value === "1";
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;
type RootLike = { setAttribute(name: string, value: string): void };

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readTextSize(storage: StorageLike | null = browserStorage()): TextSize {
  try {
    return parseTextSize(storage?.getItem(TEXT_SIZE_KEY));
  } catch {
    return "normal";
  }
}

export function readDarkerText(storage: StorageLike | null = browserStorage()): boolean {
  try {
    return parseDarkerText(storage?.getItem(DARKER_TEXT_KEY));
  } catch {
    return false;
  }
}

/** Put the two choices on <html>. Always writes both attributes, so a bad value can never leave a stale one. */
export function applyTextSettings(
  size: TextSize,
  darker: boolean,
  root: RootLike | null = typeof document === "undefined" ? null : document.documentElement,
): void {
  if (!root) return;
  root.setAttribute("data-text-size", size);
  root.setAttribute("data-darker-text", darker ? "1" : "0");
}

/** Save and apply in one go. Storage failing does not stop the change applying for this visit. */
export function saveTextSize(size: TextSize, storage: StorageLike | null = browserStorage()): void {
  try {
    storage?.setItem(TEXT_SIZE_KEY, size);
  } catch {
    /* storage blocked: the change still applies until the page closes */
  }
  applyTextSettings(size, readDarkerText(storage));
}

export function saveDarkerText(darker: boolean, storage: StorageLike | null = browserStorage()): void {
  try {
    storage?.setItem(DARKER_TEXT_KEY, darker ? "1" : "0");
  } catch {
    /* storage blocked: the change still applies until the page closes */
  }
  applyTextSettings(readTextSize(storage), darker);
}

/**
 * The tiny script app/layout.tsx puts in <head> so the saved choice is on <html> before the first paint
 * (no flash). Plain ES5 on purpose, and kept here beside the logic it repeats; the test runs it.
 */
export const TEXT_SIZE_INIT_SCRIPT =
  `(function(){var s="normal",d="0";try{var a=localStorage.getItem("${TEXT_SIZE_KEY}");` +
  `if(a==="big"||a==="bigger")s=a;if(localStorage.getItem("${DARKER_TEXT_KEY}")==="1")d="1"}catch(e){}` +
  `var r=document.documentElement;r.setAttribute("data-text-size",s);r.setAttribute("data-darker-text",d)})();`;
