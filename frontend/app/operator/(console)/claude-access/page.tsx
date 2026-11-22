import { redirect } from "next/navigation";

// The page moved to /operator/mcp. Old bookmarks keep working.
export default function ClaudeAccessRedirect() {
  redirect("/operator/mcp");
}
