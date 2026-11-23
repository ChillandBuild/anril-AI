"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Clock } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { AnrilLogo } from "@/components/logo";
import { AlertBell } from "./alert-bell";
import { ConfirmModal } from "@/components/ConfirmModal";

const NAV_ITEMS = [
  { href: "/operator", label: "Clients" },
  { href: "/operator/ai-spend", label: "AI Spend" },
  { href: "/operator/subscription", label: "Subscription" },
  { href: "/operator/subscription-requests", label: "Requests" },
  { href: "/operator/scheduler", label: "Schedulers" },
  { href: "/operator/prompt-template", label: "Master Prompt" },
  { href: "/operator/audit-log", label: "Audit Log" },
  { href: "/operator/mcp", label: "MCP" },
];

export function OperatorSidebar({ userEmail }: { userEmail: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [showSignOut, setShowSignOut] = useState(false);
  const [time, setTime] = useState("");

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" }));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut({ scope: "local" });
    router.push("/operator/login");
  }

  const initial = (userEmail || "O")[0].toUpperCase();

  return (
    <>
      <header className="sticky top-0 z-40 h-16 flex items-center justify-between gap-4 px-7 bg-white border-b border-border">
        {/* Left: Logo + Nav */}
        <div className="flex items-center gap-8">
          <div className="flex items-center gap-2">
            <AnrilLogo className="h-5 w-auto text-ink" />
            <span className="text-[10px] font-semibold text-primary uppercase tracking-[0.15em] bg-primary-light rounded px-2 py-0.5">
              Operator
            </span>
          </div>
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => {
              const isActive = item.href === "/operator"
                ? pathname === "/operator" || (pathname?.startsWith("/operator/client") ?? false)
                : pathname?.startsWith(item.href) ?? false;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-primary-light text-primary"
                      : "text-ink-secondary hover:bg-surface-mid hover:text-ink"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Right: Clock + Avatar/SignOut */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 h-[34px] px-3 text-ink font-mono text-[13px] font-semibold tracking-wide border border-border rounded-lg">
            <Clock size={13} className="opacity-50" />
            <span>{time || "00:00"}</span>
          </div>
          <AlertBell />
          <button
            onClick={() => setShowSignOut(true)}
            className="w-9 h-9 rounded-full bg-primary flex items-center justify-center text-white text-sm font-bold hover:bg-primary-dark transition-colors"
            title={userEmail}
          >
            {initial}
          </button>
        </div>
      </header>

      {/* Sign Out Confirmation */}
      <ConfirmModal
        open={showSignOut}
        onClose={() => setShowSignOut(false)}
        onConfirm={handleSignOut}
        title="Sign Out"
        description={`Are you sure you want to sign out of the operator console?\n\n${userEmail}`}
        tone="danger"
        confirmLabel="Sign Out"
      />
    </>
  );
}
