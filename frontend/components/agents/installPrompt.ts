import type { CompanionInstall } from "@/lib/api";

/**
 * A prompt the owner pastes into their AI coding tool (Cursor, Claude Code...)
 * so it installs the character on their site. Built from GET /{id}/install;
 * holds no secret: the key stays in ANRIL_COMPANION_KEY on their server.
 */
export function installPrompt(info: CompanionInstall, characterName: string): string {
  return [
    `Add the "${characterName}" chat character from Anril Agents to my website.`,
    "",
    "1. Put my Anril Agents secret key in a server environment variable named ANRIL_COMPANION_KEY. Never send it to the browser.",
    "2. Add this server function (pick the one for my backend's language) and call it for the logged-in user:",
    "",
    "Python:",
    "```python",
    info.snippets.python,
    "```",
    "",
    "Node:",
    "```js",
    info.snippets.node,
    "```",
    "",
    "3. Pass its userId, exp and signature to the page, then add this to every page where the chat should show:",
    "```html",
    info.snippets.html,
    "```",
    "",
    "Replace CURRENT_USER with however my app exposes the logged-in user. Show me the changes before applying them.",
  ].join("\n");
}
