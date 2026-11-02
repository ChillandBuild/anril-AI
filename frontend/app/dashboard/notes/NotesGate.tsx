"use client";
import type { Lead } from "@/lib/api";
import { useAuthRole } from "../contexts/AuthRoleContext";
import { NotesClient } from "./NotesClient";
import CallReview from "./review/CallReview";
import { AiraLoader } from "@/components/AiraLoader";

/** Owners and managers review the team in Call Review; telecallers keep their notes page. */
export function NotesGate({ fallbackLeads }: { fallbackLeads: { data: Lead[] } | null }) {
  const { role, permissions, loading } = useAuthRole();
  if (loading) {
    return <AiraLoader inline />;
  }
  if (role === "owner" || permissions.includes("team.manage")) return <CallReview />;
  return (
    <div className="w-full min-w-0 max-w-[1400px] overflow-x-hidden px-3 py-4 pb-28 sm:px-4 md:p-7">
      <NotesClient fallbackLeads={fallbackLeads} />
    </div>
  );
}
