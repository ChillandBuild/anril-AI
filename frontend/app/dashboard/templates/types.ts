export type Button = {
  type: 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER' | 'WHATSAPP_CALL' | 'COPY_CODE' | 'ONE_TAP' | 'FLOW';
  text: string;
  /** FLOW ("Open form"): a form id from Catalogue → Forms, or "services". */
  form_ref?: string;
  url?: string;
  phone?: string;
  country?: string;
  offer_code?: string;
  active_for_days?: number;
  autofill_text?: string;
  package_name?: string;
  signature_hash?: string;
  url_example?: string;
};

export type CarouselCard = {
  header_media_type: 'IMAGE' | 'VIDEO';
  header_media_url: string;
  body_text: string;
  buttons: Array<{ type: string; text: string; url?: string }>;
};

export type Template = {
  id: string;
  name: string;
  category: string;
  language: string;
  body_text: string;
  header_text?: string;
  header_media_type?: string;
  header_media_url?: string;
  header_media_id?: string;
  footer_text?: string;
  buttons?: Button[];
  carousel_cards?: CarouselCard[];
  // Only APPROVED is sent anywhere. DISABLED/ARCHIVED/DELETED come from Meta's status webhook.
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'PAUSED' | 'DISABLED' | 'ARCHIVED' | 'DELETED';
  meta_template_id?: string;
  short_code?: string;
  // {{n}} -> field for the WhatsApp alerts, e.g. {"1": "lead_phone"}; null = fixed order.
  variable_map?: Record<string, string> | null;
  rejection_reason?: string;
  submitted_at?: string;
  approved_at?: string;
  variations?: string[];
  // Approved templates only: Meta's edit limit (1 per 24 hours, 10 per 30 days).
  edit_allowance?: EditAllowance;
};

export type EditAllowance = {
  allowed: boolean;
  reason: 'daily' | 'monthly' | null;
  next_allowed_at: string | null;
  edits_30_days: number;
  limit_30_days: number;
};

/** When Meta lets this approved template be edited again, in India time. */
export function formatNextEdit(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
  });
}

export function detectVariables(text: string): number[] {
  const regex = /\{\{(\d+)\}\}/g;
  const nums = new Set<number>();
  let match;
  while ((match = regex.exec(text)) !== null) {
    nums.add(parseInt(match[1], 10));
  }
  return Array.from(nums).sort((a, b) => a - b);
}

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'en_US', label: 'English (US)' },
  { code: 'en_IN', label: 'English (IND)' },
  { code: 'hi', label: 'Hindi' },
  { code: 'kn', label: 'Kannada' },
  { code: 'ml', label: 'Malayalam' },
  { code: 'ta', label: 'Tamil' },
  { code: 'te', label: 'Telugu' },
] as const;

export const CATEGORIES = [
  { value: 'MARKETING', label: 'Marketing', description: 'Promotions, offers, and updates' },
  { value: 'UTILITY', label: 'Utility', description: 'Order updates, alerts, and confirmations' },
  { value: 'AUTHENTICATION', label: 'Authentication', description: 'OTP and verification codes' },
] as const;

export const STATUS_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  APPROVED: { bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  PENDING: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-500' },
  REJECTED: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500' },
  PAUSED: { bg: 'bg-[#f1f5f9]', text: 'text-[#334155]', dot: 'bg-[#94a3b8]' },
  DISABLED: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500' },
  ARCHIVED: { bg: 'bg-[#f1f5f9]', text: 'text-[#334155]', dot: 'bg-[#94a3b8]' },
  DELETED: { bg: 'bg-[#f1f5f9]', text: 'text-[#64748b]', dot: 'bg-[#cbd5e1]' },
};

export const CATEGORY_COLORS: Record<string, { bg: string; text: string }> = {
  MARKETING: { bg: 'bg-purple-50', text: 'text-purple-700' },
  UTILITY: { bg: 'bg-blue-50', text: 'text-blue-700' },
  AUTHENTICATION: { bg: 'bg-teal-50', text: 'text-teal-700' },
};

/** One place a template is used (GET /api/v1/templates/usage). `ended`: it was used there, but isn't now. */
export type UsageEntry = { area: string; label: string; href: string; ended?: boolean };
export type TemplateUsage = Record<string, UsageEntry[]>;

/** "English", "Tamil"... for a language code; an unknown code is shown as it is. */
export function languageName(code: string): string {
  return LANGUAGES.find((l) => l.code === code)?.label ?? code;
}
