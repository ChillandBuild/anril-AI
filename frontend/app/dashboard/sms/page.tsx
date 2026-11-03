import Link from "next/link";
import { Card, CardHeader } from "./ui";

// Placeholder until the real dashboard (cards, stats, upcoming sends) lands.
const PAGES = [
  { href: "/dashboard/sms/setup", label: "DLT Setup" },
  { href: "/dashboard/sms/send", label: "Send SMS" },
  { href: "/dashboard/sms/contacts", label: "Address Book" },
  { href: "/dashboard/sms/reports", label: "Delivery Reports" },
  { href: "/dashboard/sms/transactions", label: "Transactions" },
  { href: "/dashboard/sms/developer", label: "Dev API" },
  { href: "/dashboard/sms/otp", label: "Smart OTP" },
];

export default function SmsDashboardPage() {
  return (
    <Card>
      <CardHeader title="Dashboard" hint="Your SMS overview is coming here. Jump to a page:" />
      <ul className="grid gap-2 p-4 sm:grid-cols-2 sm:p-5">
        {PAGES.map((p) => (
          <li key={p.href}>
            <Link href={p.href} className="block rounded-xl border border-[#e2e8f0] px-4 py-3 text-sm font-bold text-primary hover:bg-primary/5">
              {p.label}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
