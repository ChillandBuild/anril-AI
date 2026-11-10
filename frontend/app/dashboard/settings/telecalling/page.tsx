import { redirect } from "next/navigation";

// TeleCMI credentials live on the Telecalling behaviour page —
// kept as a redirect so any bookmarked or hardcoded link still lands somewhere useful.
export default function TelecallingCredentialsRedirect() {
  redirect("/dashboard/settings/telecalling-behavior#calling");
}
