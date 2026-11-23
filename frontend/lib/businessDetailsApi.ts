import { API_URL, apiFetch, errorDetailText, getAuthHeaders } from "@/lib/api";

/**
 * Settings > Business details & bills (backend routes/business_details.py).
 * lib/api.ts is not touched: this file has its own calls on the same apiFetch.
 */

export type GstType = "regular" | "composition" | "none";
export type BrandImageKind = "logo" | "signature";

export interface BusinessDetails {
  legal_name: string;
  bill_name: string;
  address: string;
  city: string;
  state: string;
  state_code: string;
  pincode: string;
  gstin: string;
  pan: string;
  gst_type: GstType;
  email: string;
  phone: string;
  prices_include_gst: boolean;
  bill_prefix: string;
  licence_number: string;
  terms: string;
  upi_id: string;
  bank_account_name: string;
  bank_name: string;
  bank_ifsc: string;
  /** Only the last 4 digits ("••••1234") unless you can manage settings. */
  bank_account_number: string;
  has_logo?: boolean;
  has_signature?: boolean;
  logo_url?: string | null;
  signature_url?: string | null;
}

export const EMPTY_BUSINESS_DETAILS: BusinessDetails = {
  legal_name: "",
  bill_name: "",
  address: "",
  city: "",
  state: "",
  state_code: "",
  pincode: "",
  gstin: "",
  pan: "",
  gst_type: "regular",
  email: "",
  phone: "",
  prices_include_gst: true,
  bill_prefix: "",
  licence_number: "",
  terms: "",
  upi_id: "",
  bank_account_name: "",
  bank_name: "",
  bank_ifsc: "",
  bank_account_number: "",
};

/** What a save sends: the typed fields only (pictures go through their own upload). */
export type BusinessDetailsDraft = Omit<BusinessDetails, "has_logo" | "has_signature" | "logo_url" | "signature_url">;

/** Older backends send fewer fields: fill the gaps so a screen never reads undefined. */
export function withDefaults(data: Partial<BusinessDetails> | null | undefined): BusinessDetails {
  return { ...EMPTY_BUSINESS_DETAILS, ...(data ?? {}) };
}

export function fetchBusinessDetails(): Promise<BusinessDetails> {
  return apiFetch<Partial<BusinessDetails>>("/api/v1/business-details").then(withDefaults);
}

export function saveBusinessDetails(draft: BusinessDetailsDraft): Promise<BusinessDetails> {
  return apiFetch<Partial<BusinessDetails>>("/api/v1/business-details", {
    method: "PUT",
    body: JSON.stringify(draft),
  }).then(withDefaults);
}

export async function uploadBrandImage(kind: BrandImageKind, file: File): Promise<BusinessDetails> {
  const fd = new FormData();
  fd.append("file", file);
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/business-details/image/${kind}`, { method: "POST", body: fd, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(errorDetailText(err?.detail, "Couldn't upload the picture"));
  }
  return withDefaults(await res.json());
}

export function removeBrandImage(kind: BrandImageKind): Promise<BusinessDetails> {
  return apiFetch<Partial<BusinessDetails>>(`/api/v1/business-details/image/${kind}`, { method: "DELETE" }).then(withDefaults);
}

/** The same limits as the server: 1 MB, PNG / JPG / WEBP. Returns a plain-English problem or null. */
export function imageProblem(file: { size: number; type: string }): string | null {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) return "Pick a PNG, JPG or WEBP picture.";
  if (file.size > 1024 * 1024) return "The picture must be under 1 MB.";
  return null;
}
