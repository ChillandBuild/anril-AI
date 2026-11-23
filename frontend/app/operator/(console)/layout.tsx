import { redirect } from "next/navigation";
import { createOperatorClient } from "@/lib/supabase/server";
import { OperatorSidebar } from "./components/operator-sidebar";
import { BackendUnreachable } from "./components/backend-unreachable";
import { CommandPalette } from "./components/command-palette";

const ME_FETCH_TIMEOUT_MS = 8000;

export default async function OperatorLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createOperatorClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/operator/login");

  const { data: { session } } = await supabase.auth.getSession();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  let isAdmin = false;
  let unauthorized = false;
  let unreachable = false;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), ME_FETCH_TIMEOUT_MS);
    let meRes: Response;
    try {
      meRes = await fetch(`${apiUrl}/api/v1/operator/me`, {
        headers: { Authorization: `Bearer ${session?.access_token}` },
        cache: "no-store",
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }

    if (meRes.status === 401 || meRes.status === 403) {
      unauthorized = true;
    } else if (meRes.ok) {
      const me = await meRes.json();
      isAdmin = me.is_system_admin === true;
    } else {
      // Non-ok, non-401/403 (e.g. 5xx) — treat as infra failure, not an auth failure.
      unreachable = true;
    }
  } catch {
    // Network error, abort, or timeout — infra failure, not an auth failure.
    unreachable = true;
  }

  if (unauthorized) redirect("/operator/login");
  if (unreachable) return <BackendUnreachable />;
  if (!isAdmin) redirect("/dashboard");

  return (
    <div className="min-h-screen bg-background">
      <OperatorSidebar userEmail={user.email || ""} />
      <CommandPalette />
      <main className="min-h-[calc(100vh-4rem)]">
        {children}
      </main>
    </div>
  );
}
