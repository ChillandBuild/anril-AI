/**
 * What a GSTIN tells you for free, with no lookup: the state (first two digits), the PAN
 * (characters 3 to 12) and whether the last character matches (the GST check digit).
 * The business name and address need a paid GST lookup; that comes later.
 */

export const GST_STATES: Record<string, string> = {
  "01": "Jammu and Kashmir",
  "02": "Himachal Pradesh",
  "03": "Punjab",
  "04": "Chandigarh",
  "05": "Uttarakhand",
  "06": "Haryana",
  "07": "Delhi",
  "08": "Rajasthan",
  "09": "Uttar Pradesh",
  "10": "Bihar",
  "11": "Sikkim",
  "12": "Arunachal Pradesh",
  "13": "Nagaland",
  "14": "Manipur",
  "15": "Mizoram",
  "16": "Tripura",
  "17": "Meghalaya",
  "18": "Assam",
  "19": "West Bengal",
  "20": "Jharkhand",
  "21": "Odisha",
  "22": "Chhattisgarh",
  "23": "Madhya Pradesh",
  "24": "Gujarat",
  "25": "Daman and Diu",
  "26": "Dadra and Nagar Haveli and Daman and Diu",
  "27": "Maharashtra",
  "28": "Andhra Pradesh",
  "29": "Karnataka",
  "30": "Goa",
  "31": "Lakshadweep",
  "32": "Kerala",
  "33": "Tamil Nadu",
  "34": "Puducherry",
  "35": "Andaman and Nicobar Islands",
  "36": "Telangana",
  "37": "Andhra Pradesh",
  "38": "Ladakh",
  "97": "Other Territory",
};

const SHAPE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/** The 15th character a GSTIN must end with, worked out from the first 14. */
export function gstinCheckChar(first14: string): string {
  let sum = 0;
  for (let i = 0; i < 14; i++) {
    const p = CHARS.indexOf(first14[i]) * (i % 2 === 0 ? 1 : 2);
    sum += Math.floor(p / 36) + (p % 36);
  }
  return CHARS[(36 - (sum % 36)) % 36];
}

export type GstinRead =
  | { status: "empty" }
  | { status: "typing" }
  | { status: "bad"; message: string }
  | { status: "ok"; gstin: string; stateCode: string; stateName: string; pan: string; checkMatches: boolean };

/** Read a GSTIN as it is being typed. "typing" until all 15 characters are in. */
export function readGstin(raw: string | null | undefined): GstinRead {
  const s = (raw ?? "").replace(/\s/g, "").toUpperCase();
  if (!s) return { status: "empty" };
  if (s.length < 15) return { status: "typing" };
  if (!SHAPE.test(s)) return { status: "bad", message: "That doesn't look like a GSTIN. It has 15 characters, like 33ABCDE1234F1Z5." };
  const stateCode = s.slice(0, 2);
  const stateName = GST_STATES[stateCode];
  if (!stateName) return { status: "bad", message: `${stateCode} isn't a GST state code. Check the first two digits.` };
  return {
    status: "ok",
    gstin: s,
    stateCode,
    stateName,
    pan: s.slice(2, 12),
    checkMatches: gstinCheckChar(s.slice(0, 14)) === s[14],
  };
}

/** The fields a good GSTIN fills in. The state name is changed only if it was empty or another known state. */
export function fillFromGstin(
  read: GstinRead,
  current: { state?: string | null },
): { state_code: string; pan: string; state?: string } | null {
  if (read.status !== "ok") return null;
  const now = (current.state ?? "").trim();
  const known = Object.values(GST_STATES).some((n) => n.toLowerCase() === now.toLowerCase());
  return {
    state_code: read.stateCode,
    pan: read.pan,
    ...(!now || known ? { state: read.stateName } : {}),
  };
}
