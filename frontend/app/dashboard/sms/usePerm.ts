"use client";

import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";

/** Owner can do everything; everyone else needs the named permission. */
export function usePerm() {
  const { role, permissions, loading } = useAuthRole();
  const isOwner = role === "owner";
  const can = (perm: string) => isOwner || permissions.includes(perm);
  return {
    loading,
    isOwner,
    can,
    canView: can("sms.view") || can("sms.manage"),
    canManage: can("sms.manage"),
    canRecharge: can("sms.recharge"),
  };
}
