import { Suspense } from "react";
import { Skeleton } from "../../sms/ui";
import { HistoryTab } from "../HistoryTab";

export default function OtpHistoryPage() {
  return (
    <div className="w-full">
      <Suspense fallback={<Skeleton className="h-96" />}>
        <HistoryTab />
      </Suspense>
    </div>
  );
}
