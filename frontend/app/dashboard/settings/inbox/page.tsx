import { redirect } from "next/navigation";

export default function InboxSettingsPage() {
  redirect("/dashboard/settings/auto-reply");
}
