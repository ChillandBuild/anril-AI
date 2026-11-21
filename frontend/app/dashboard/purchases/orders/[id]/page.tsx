"use client";

import { useParams } from "next/navigation";
import { AiraLoader } from "@/components/AiraLoader";
import { usePurchaseOrder } from "@/hooks/useApi";
import { PoEditor } from "../../PoEditor";

export default function PurchaseOrderPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = usePurchaseOrder(id);
  if (error) return <p className="text-sm text-danger">Couldn&apos;t open this purchase order.</p>;
  if (!data) return <AiraLoader inline className="min-h-[50vh]" />;
  return <PoEditor key={data.id + data.status} po={data} />;
}
