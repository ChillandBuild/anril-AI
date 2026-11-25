"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";

/** The signed-in person's email and a display name (their full name, else one made from the email). */
export function useCurrentUser() {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const { data } = await createClient().auth.getUser();
      if (!alive) return;
      const userEmail = data.user?.email ?? "";
      setEmail(userEmail);
      const metaName = data.user?.user_metadata?.full_name;
      if (metaName) {
        setFullName(metaName);
      } else {
        const parts = userEmail.split("@")[0].split(/[._-]/);
        setFullName(parts.map((p: string) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ") || "User");
      }
    };
    void load();
    return () => {
      alive = false;
    };
  }, []);

  return { email, fullName };
}
