import type { CompanionOverview } from "@/lib/api";

export type SetupStep = { id: "live" | "key" | "seen"; title: string; detail: string; done: boolean; href: string; action: string };

/**
 * The three setup steps. Example: a business has Maya live and a key,
 * but no site call yet → steps 1 and 2 done, step 3 points at Install.
 */
export function setupSteps(o: CompanionOverview): SetupStep[] {
  return [
    {
      id: "live",
      title: "Make a character live",
      detail: o.live_characters > 0 ? `${o.live_characters} live` : "Write its persona and set it Live.",
      done: o.live_characters > 0,
      href: "/dashboard/agents/characters",
      action: o.characters > 0 ? "Open characters" : "Create a character",
    },
    {
      id: "key",
      title: "Create a secret key",
      detail: o.active_keys > 0 ? `${o.active_keys} active` : "Your server uses it to sign people in.",
      done: o.active_keys > 0,
      href: "/dashboard/agents/keys",
      action: "Create key",
    },
    {
      id: "seen",
      title: "Seen on your site",
      detail: o.key_last_used_at ? "Your site has called your character." : "Install the widget; this ticks on the first call.",
      done: o.key_last_used_at !== null,
      href: "/dashboard/agents/install",
      action: "Install",
    },
  ];
}
