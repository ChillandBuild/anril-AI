import { Suspense } from "react";
import { ContactsTab } from "../ContactsTab";
import { Skeleton } from "../ui";

export default function SmsContactsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <ContactsTab />
    </Suspense>
  );
}
