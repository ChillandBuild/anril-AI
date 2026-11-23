"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { toast } from "sonner";
import { propertiesApi, type PropertyBody } from "@/lib/propertiesApi";
import { useAuthRole } from "../../../contexts/AuthRoleContext";
import { PropertyForm } from "../PropertyForm";

export default function NewPropertyPage() {
  const router = useRouter();
  const { role, permissions, loading } = useAuthRole();
  const canManage = role === "owner" || permissions.includes("catalog.manage");
  const canSeeMoney = role === "owner" || permissions.includes("deals.view") || permissions.includes("deals.manage");
  const [saving, setSaving] = useState(false);

  async function save(body: PropertyBody) {
    setSaving(true);
    try {
      const made = await propertiesApi.create(body);
      toast.success("Property added. Add photos and a brochure next.");
      router.push(`/dashboard/catalog/properties/${made.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save this property");
      setSaving(false);
    }
  }

  if (loading) return <div className="min-h-[200px] animate-pulse rounded-card bg-surface-low" />;
  if (!canManage) return <p className="py-16 text-center text-sm text-ink-muted">You do not have access to add properties.</p>;

  return (
    <div className="w-full space-y-4">
      <Link href="/dashboard/catalog/properties" className="inline-flex items-center gap-1 text-sm font-semibold text-primary">
        <ChevronLeft className="h-4 w-4" aria-hidden /> Properties
      </Link>
      <h1 className="text-lg font-bold text-ink">Add a property</h1>
      <PropertyForm canSeeMoney={canSeeMoney} saving={saving} submitLabel="Save property" onSubmit={save} />
    </div>
  );
}
