"use client";
import { useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import { mustChangePassword } from "./helpers";

/**
 * Drop this into the dashboard layout. If the Anril team made this login and the owner has not yet
 * chosen their own password, it sends them to /change-password. It is a helper for the owner, not a
 * security wall: anyone can walk past it, and nothing on the server depends on it.
 */
export function MustChangePasswordGate() {
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const { data } = await createClient().auth.getUser();
        if (!cancelled && mustChangePassword(data.user)) window.location.replace("/change-password");
      } catch {
        // Offline or signed out: the dashboard handles that itself.
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, []);
  return null;
}
