"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { LogOut, MessageSquarePlus, TrendingUp, UserCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { useLogout } from "@/hooks/useLogout";
import { FeedbackModal } from "@/components/FeedbackModal";

export function ProfileMenu() {
  const { tenantName, role } = useAuthRole();
  const isTelecaller = role === "caller";
  const [email, setEmail] = useState<string>("");
  const [fullName, setFullName] = useState<string>("");
  const [open, setOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    const loadUser = async () => {
      const { data } = await supabase.auth.getUser();
      const userEmail = data.user?.email ?? "";
      setEmail(userEmail);

      const metaName = data.user?.user_metadata?.full_name;
      if (metaName) {
        setFullName(metaName);
      } else {
        const parts = userEmail.split("@")[0].split(/[._-]/);
        const capitalized = parts.map((p: string) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
        setFullName(capitalized || "User");
      }
    };
    loadUser();
  }, []);

  const logout = useLogout();
  const initials = email ? email.charAt(0).toUpperCase() : "U";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full py-0.5 pl-0.5 pr-1 transition-colors hover:bg-[#f1f5f9]"
        title={tenantName ?? undefined}
      >
        <span
          className="flex items-center justify-center w-[34px] h-[34px] shrink-0 rounded-full text-[#0A1528] text-[12px] font-bold"
          style={{ background: "var(--primary-400)" }}
        >
          {initials}
        </span>
        {tenantName && (
          <span className="hidden max-w-[150px] truncate font-body text-sm font-semibold text-[#0A1528] sm:block">
            {tenantName}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-2 w-64 bg-white border border-[#e2e8f0] rounded-2xl shadow-xl z-50 overflow-hidden py-1">
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[#f1f5f9]">
              <div className="flex-shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-yellow-100 text-yellow-800 font-bold text-sm">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-[#0A1528] truncate">{tenantName || fullName}</p>
                <p className="text-xs text-[#475569] truncate">{email}</p>
              </div>
            </div>

            <div className="py-1">
              <Link
                href="/dashboard/settings/account"
                onClick={() => setOpen(false)}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-[#13284A] hover:bg-[#f8fafc] transition-colors text-left"
              >
                <UserCircle size={16} className="text-[#475569]" />
                <span>Profile & Business</span>
              </Link>
              {isTelecaller && (
                <Link
                  href="/dashboard/profile"
                  onClick={() => setOpen(false)}
                  className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-[#13284A] hover:bg-[#f8fafc] transition-colors text-left"
                >
                  <TrendingUp size={16} className="text-[#475569]" />
                  <span>My performance</span>
                </Link>
              )}
              <button
                onClick={() => {
                  setOpen(false);
                  setFeedbackOpen(true);
                }}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-[#13284A] hover:bg-[#f8fafc] transition-colors text-left"
              >
                <MessageSquarePlus size={16} className="text-[#475569]" />
                <span>Feedback</span>
              </button>
            </div>

            <div className="border-t border-[#f1f5f9] my-1" />

            <div className="py-1">
              <button onClick={logout} className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-[#13284A] hover:bg-[#f8fafc] transition-colors text-left">
                <LogOut size={16} className="text-[#475569]" />
                <span>Sign out</span>
              </button>
            </div>
          </div>
        </>
      )}
      <FeedbackModal open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </div>
  );
}
