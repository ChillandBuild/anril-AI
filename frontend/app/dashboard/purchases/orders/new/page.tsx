"use client";

import { useSearchParams } from "next/navigation";
import { AiraLoader } from "@/components/AiraLoader";
import { useReorderSuggestionsOnce } from "../../useReorder";
import { PoEditor } from "../../PoEditor";

/* New purchase order. ?suggest=1 (from "5 items are low") fills in the reorder suggestions. */
export default function NewPurchaseOrderPage() {
  const suggest = useSearchParams().get("suggest") === "1";
  const { data, loading } = useReorderSuggestionsOnce(suggest);
  if (suggest && loading) return <AiraLoader inline className="min-h-[50vh]" />;
  return <PoEditor suggestions={suggest ? data : undefined} />;
}
