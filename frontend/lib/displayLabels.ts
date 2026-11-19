// Customer-facing labels. Never show raw feature keys or supplier names.

const FEATURE_LABELS: Record<string, string> = {
  ai_speech_to_text: "Voice notes understood",
  ai_text_to_speech: "AI voice replies",
};

/** Readable name for a plan feature: server display name first, then our map, then humanised key. */
export function featureLabel(key: string, displayName?: string | null): string {
  const mapped = FEATURE_LABELS[key];
  if (mapped) return mapped;
  const name = displayName?.trim();
  if (name) return maskSupplier(name);
  const words = key.replace(/[_\-.]+/g, " ").trim().toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

/** Replace the calling supplier's name in any server-provided text. */
export function maskSupplier(text: string): string {
  const name = String.raw`Tele[\s\-‐-―]?CMI`;
  return text
    // "Telecalling — Tele-CMI" and "Calling (TeleCMI)" become just "Cloud calling".
    .replace(new RegExp(String.raw`^\s*(?:Tele)?calling\s*(?:[—–\-:]\s*${name}|\(\s*${name}\s*\))\s*$`, "i"), "Cloud calling")
    .replace(new RegExp(name, "gi"), "Cloud calling");
}

/** Rupee amount for display: en-IN grouping, at most 2 decimals. */
export function formatRupees(n: number): string {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
