"use client";

import { Suspense } from "react";
import { DltManagerTab } from "../DltManagerTab";
import { Skeleton } from "../ui";

// DLT Setup: Entity ID, Sender ID and Content Template as sub-tabs (?sub=entities|senders|templates).
// Old links (?tab=entity, ?tab=petm, ?tab=manager&sub=X) are mapped by setupSubFor in DltManagerTab.
export default function SmsSetupPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <DltManagerTab />
    </Suspense>
  );
}
