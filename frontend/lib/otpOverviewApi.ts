import { apiFetch } from "@/lib/api";

// Anril OTP › Overview (GET /api/v1/otp-overview). Read-only; shapes mirror
// backend/app/services/otp_overview.py.

export type OtpOverviewMonth = {
  sent: number;
  prev_month_sent: number;
  /** Whole percent against last month; null when last month had no codes. */
  change_pct: number | null;
  verified: number;
  /** Whole percent of Anril-made codes that were used; null when Anril made none. */
  used_pct: number | null;
  by_sms: number;
  by_whatsapp: number;
  backups: number;
  locked: number;
  not_requested: number;
  failed: number;
};

export type OtpOverviewDay = { day: string; sent: number; verified: number };

export type OtpOverviewSource = {
  /** Stable and unique within the list (the API key id or the place the code came from). */
  key: string;
  label: string; sent: number;
  used_pct: number | null;
};

export type OtpOverviewBalance = { sms_left: number | null; checked_at: string | null; low_below: number };

export type OtpOverviewHealth = {
  key: string;
  label: string;
  /** true = working, false = needs a look, null = not set up or couldn't be checked. */
  ok: boolean | null;
  detail: string;
};

export type OtpOverview = {
  /** false when the code history couldn't be read: the numbers are zeros, not real. */
  available: boolean;
  month: OtpOverviewMonth;
  daily_7: OtpOverviewDay[];
  sources: OtpOverviewSource[];
  balance: OtpOverviewBalance;
  health: OtpOverviewHealth[];
  in_short: string;
};

export function fetchOtpOverview(): Promise<OtpOverview> {
  return apiFetch<OtpOverview>("/api/v1/otp-overview");
}
