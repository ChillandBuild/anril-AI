"use client";
import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { API_URL, getAuthHeaders } from "@/lib/api";
import { clearRoleCache } from "@/app/dashboard/contexts/AuthRoleContext";
import { createClient } from "@/lib/supabase/client";

export function useLogout() {
  const router = useRouter();
  return useCallback(async () => {
    if (!confirm("Are you sure you want to sign out?")) return;
    clearRoleCache();
    // Set telecaller status to logged_out before signing out
    try {
      const headers = await getAuthHeaders();
      await fetch(`${API_URL}/api/v1/callers/my-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify({ status: "logged_out" }),
      });
    } catch {}
    const supabase = createClient();
    await supabase.auth.signOut({ scope: "local" });
    router.push("/login");
    router.refresh();
  }, [router]);
}
