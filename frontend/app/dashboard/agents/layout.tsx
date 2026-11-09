"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { canSeeAgents } from "@/components/nav/products";

/** Anril Agents pages need companions.manage; anyone else is sent to the dashboard. */
export default function AgentsLayout({ children }: { children: React.ReactNode }) {
  const { role, permissions, loading } = useAuthRole();
  const router = useRouter();
  const allowed = canSeeAgents(role, permissions);

  useEffect(() => {
    if (!loading && !allowed) router.replace("/dashboard");
  }, [loading, allowed, router]);

  if (loading || !allowed) return null;
  return <>{children}</>;
}
