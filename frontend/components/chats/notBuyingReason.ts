/** "Not buying" > "Other…": the team types the reason in their own words. The server trims and cuts at the same length. */
export const OTHER_REASON_MAX = 120;

/** Extra spaces and line breaks collapsed, cut at OTHER_REASON_MAX. Empty when nothing real was typed. */
export function cleanOtherReason(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ").slice(0, OTHER_REASON_MAX).trim();
}
