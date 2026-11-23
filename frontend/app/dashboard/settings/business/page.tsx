import { redirect } from "next/navigation";

// Merged into "Profile & Business" — kept as a redirect so any bookmarked or
// hardcoded link to this URL still lands somewhere useful.
export default function BusinessSettingsRedirect() {
  redirect("/dashboard/settings/account");
}
