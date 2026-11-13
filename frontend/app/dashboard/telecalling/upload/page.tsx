"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Upload,
  Download,
  FileText,
  Loader2,
  Plus,
  Pencil,
  Trash2,
  Eye,
  ChevronRight,
  X,

  GitBranch,

  ToggleLeft,
  ToggleRight,
  Check,
  CloudUpload,
} from "lucide-react";
import { getAuthHeaders } from "@/lib/api";
import { convertScanToCsv } from "@/lib/scanUpload";
import { cn } from "@/lib/utils";
import { Select } from "@/components/ui/Select";
import { useSearchParams } from "next/navigation";
import { createPortal } from "react-dom";

function Portal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) return null;
  return createPortal(children, document.body);
}


const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "https://aira-ai-5tfr.onrender.com";

// ─── Types ───────────────────────────────────────────────────────────────────

interface UploadResult {
  batch_id: string;
  total: number;
  inserted: number;
  duplicates: number;
  assigned: number;
}

interface ParsedData {
  columns: string[];
  suggested_mapping: { name: string | null; phone: string | null; email: string | null; course: string | null };
  total_rows: number;
  duplicate_count: number;
  preview: Record<string, string>[];
  csv_file_url: string | null;
  csv_file_path: string | null;
  csv_file_name: string | null;
}

interface HistoryItem {
  id: string;
  file_name: string;
  total_contacts: number;
  inserted: number;
  duplicates: number;
  assigned: number;
  segment_override: string | null;
  created_at: string;
}

interface Branch {
  label: string;
  goto: number;
}

interface Step {
  order: number;
  text: string;
  note?: string;
  branches?: Branch[];
}

interface CallScript {
  id: string;
  name: string;
  segment: string | null;
  steps: Step[];
  is_default: boolean;
  active: boolean;
  created_at: string;
}

type FormStep = { text: string; note: string; branches: Branch[] };

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: "Asia/Kolkata",
  }).format(new Date(dateStr));
}

async function toCsvFile(file: File): Promise<File> {
  const lower = file.name.toLowerCase();
  if (!lower.endsWith(".xlsx") && !lower.endsWith(".xls")) return file;
  const XLSX = await import("xlsx");
  const wb = XLSX.read(await file.arrayBuffer(), { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  if (!ws) throw new Error("The spreadsheet has no sheets");
  const csv = XLSX.utils.sheet_to_csv(ws, { blankrows: false, rawNumbers: false });
  return new File([csv], file.name.replace(/\.(xlsx|xls)$/i, ".csv"), { type: "text/csv" });
}

function findPhoneAndNameColumns(headers: string[]): { phone: string | null; name: string | null } {
  let phone: string | null = null;
  let name: string | null = null;

  // 1. Exact match (case insensitive, stripped)
  for (const h of headers) {
    const hl = h.toLowerCase().trim();
    if (hl === "phone" || hl === "mobile" || hl === "contact" || hl === "number" || hl === "phone_number" || hl === "phone number") {
      phone = h;
    }
    if (hl === "name" || hl === "full name" || hl === "fullname" || hl === "customer name" || hl === "lead name") {
      name = h;
    }
  }

  // 2. Substring match if not found yet
  if (!phone) {
    for (const h of headers) {
      const hl = h.toLowerCase().trim();
      if (hl.includes("phone") || hl.includes("mobile") || hl.includes("contact") || hl.includes("number") || hl.includes("num") || hl.includes("cell") || hl.includes("tel")) {
        phone = h;
        break;
      }
    }
  }
  if (!name) {
    for (const h of headers) {
      const hl = h.toLowerCase().trim();
      if (hl.includes("name") || hl.includes("lead") || hl.includes("customer") || hl.includes("client")) {
        name = h;
        break;
      }
    }
  }

  return { phone, name };
}

function parseCsvHeaders(firstLine: string): string[] {
  const headers: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < firstLine.length; i++) {
    const char = firstLine[i];
    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      headers.push(current.trim().replace(/^"|"$/g, ""));
      current = "";
    } else {
      current += char;
    }
  }
  headers.push(current.trim().replace(/^"|"$/g, ""));
  return headers;
}

async function normalizeCsvFile(file: File): Promise<{ normalizedFile: File; columns: string[]; phoneColumn: string | null; nameColumn: string | null }> {
  const text = await file.text();
  const firstNewlineIdx = text.search(/\r?\n/);
  if (firstNewlineIdx === -1) {
    throw new Error("CSV file is empty or has no headers");
  }
  const firstLine = text.substring(0, firstNewlineIdx);
  const remaining = text.substring(firstNewlineIdx);

  const headers = parseCsvHeaders(firstLine);
  const { phone: detectedPhoneCol, name: detectedNameCol } = findPhoneAndNameColumns(headers);

  if (!detectedPhoneCol) {
    throw new Error("Could not find a phone number column in the file. Please ensure there is a column like 'phone', 'mobile', or 'contact'.");
  }

  const newHeaders = headers.map(h => {
    if (h === detectedPhoneCol) return "phone";
    if (h === detectedNameCol) return "name";
    return h;
  });

  const newHeaderLine = newHeaders.map(h => `"${h.replace(/"/g, '""')}"`).join(",");
  const newContent = newHeaderLine + remaining;

  const normalizedFile = new File([newContent], file.name, { type: "text/csv" });
  return {
    normalizedFile,
    columns: headers,
    phoneColumn: detectedPhoneCol,
    nameColumn: detectedNameCol
  };
}

function emptyFormStep(): FormStep {
  return { text: "", note: "", branches: [] };
}

function stepsToForm(steps: Step[]): FormStep[] {
  if (!steps.length) return [emptyFormStep()];
  return steps
    .sort((a, b) => a.order - b.order)
    .map((s) => ({ text: s.text, note: s.note ?? "", branches: s.branches ?? [] }));
}

function formToSteps(form: FormStep[]): Step[] {
  return form.map((f, i) => ({
    order: i + 1,
    text: f.text,
    ...(f.note ? { note: f.note } : {}),
    ...(f.branches.length ? { branches: f.branches } : {}),
  }));
}

// ─── Script API helpers ──────────────────────────────────────────────────────

async function fetchScripts(): Promise<CallScript[]> {
  try {
    const headers = await getAuthHeaders();
    const res = await fetch(`${API_URL}/api/v1/call-scripts`, {
      headers: { "Content-Type": "application/json", ...headers },
    });
    if (!res.ok) return [];
    const raw = await res.json();
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

async function apiCreateScript(body: {
  name: string;
  segment?: string | null;
  steps: Step[];
  is_default: boolean;
}): Promise<CallScript> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/call-scripts`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Create failed" }));
    throw new Error(err.detail || "Create failed");
  }
  return res.json();
}

async function apiUpdateScript(
  id: string,
  body: Partial<{ name: string; segment: string | null; steps: Step[]; is_default: boolean; active: boolean }>
): Promise<CallScript> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/call-scripts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Update failed" }));
    throw new Error(err.detail || "Update failed");
  }
  return res.json();
}

async function apiDeleteScript(id: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}/api/v1/call-scripts/${id}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json", ...headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Delete failed" }));
    throw new Error(err.detail || "Delete failed");
  }
}

// ─── Step Indicator ──────────────────────────────────────────────────────────

const WIZARD_STEPS = ["Upload", "Confirm"];

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-start w-full mb-10">
      {WIZARD_STEPS.map((label, i) => {
        const step = i + 1;
        const done = step < current;
        const active = step === current;
        return (
          <div key={label} className="flex-1 flex flex-col items-center relative">
            {i > 0 && (
              <div className={cn("absolute top-5 right-1/2 w-full h-0.5 -translate-y-1/2 transition-colors", step <= current ? "bg-primary" : "bg-surface-mid")} />
            )}
            <div className={cn(
              "relative z-10 w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all",
              done ? "bg-gradient-to-br from-[var(--primary-950)] to-primary text-white shadow-sm" : active ? "bg-gradient-to-br from-[var(--primary-950)] to-primary text-white ring-4 ring-primary/20 shadow-md" : "bg-surface text-on-surface-muted border-2 border-surface-mid"
            )}>
              {done ? <Check size={16} /> : step}
            </div>
            <span className={cn(
              "mt-2 font-label text-xs text-center whitespace-nowrap",
              active ? "text-primary font-semibold" : done ? "text-primary/50" : "text-on-surface-muted"
            )}>
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function TelecallingUploadPage() {
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab = (rawTab === "history" || rawTab === "scripts" ? rawTab : "upload") as "upload" | "history" | "scripts";



  return (
    <div>
      {activeTab === "upload" && <UploadTab />}
      {activeTab === "history" && <HistoryTab />}
      {activeTab === "scripts" && <ScriptsTab />}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// UPLOAD TAB — 3-step wizard
// ═══════════════════════════════════════════════════════════════════════════════

function UploadTab() {
  const [currentStep, setCurrentStep] = useState(1);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Count rows by reading the file
  const [rowCount, setRowCount] = useState<number | null>(null);

  const [parsedData, setParsedData] = useState<ParsedData | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  async function processAndParseFile(selected: File) {
    setFile(null);
    setUploadResult(null);
    setUploadError(null);
    setRowCount(null);
    setParsedData(null);
    setParseError(null);
    setParseLoading(true);

    try {
      const lowerName = selected.name.toLowerCase();
      const isScan = lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg") || lowerName.endsWith(".png") || lowerName.endsWith(".pdf");

      // 1. OCR a photo/PDF scan into CSV first, otherwise convert Excel to CSV if needed
      const csvFile = isScan ? await convertScanToCsv(selected) : await toCsvFile(selected);

      // 2. Normalize CSV headers client-side (maps phone/name columns)
      const { normalizedFile } = await normalizeCsvFile(csvFile);
      setFile(normalizedFile);

      // 3. Call backend parsing endpoint to extract contacts info (duplicate count, preview, etc.)
      const auth = await getAuthHeaders();
      const fd = new FormData();
      fd.append("file", normalizedFile);

      const res = await fetch(`${API_URL}/api/v1/upload/parse`, {
        method: "POST",
        body: fd,
        headers: { ...auth },
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || `Failed to parse CSV file (${res.status})`);
      }

      const data: ParsedData = await res.json();
      setParsedData(data);
      setRowCount(data.total_rows);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "Failed to process and parse file");
    } finally {
      setParseLoading(false);
    }
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null;
    if (!selected) return;
    await processAndParseFile(selected);
  }

  async function handleDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (!dropped) return;

    const lowerName = dropped.name.toLowerCase();
    if (lowerName.endsWith(".csv") || lowerName.endsWith(".xlsx") || lowerName.endsWith(".xls") || lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg") || lowerName.endsWith(".png") || lowerName.endsWith(".pdf")) {
      await processAndParseFile(dropped);
    } else {
      setParseError("Invalid file format. Please upload a .csv, .xlsx, .xls, .jpg, .png, or .pdf file.");
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    setUploadError(null);
    try {
      const headers = await getAuthHeaders();
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_URL}/api/v1/telecalling-upload/upload`, {
        method: "POST",
        body: fd,
        headers: { ...headers },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail || `Upload failed (${res.status})`);
      }
      const result: UploadResult = await res.json();
      setUploadResult(result);
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function handleReset() {
    setFile(null);
    setCurrentStep(1);
    setUploadResult(null);
    setUploadError(null);
    setRowCount(null);
    setParsedData(null);
    setParseError(null);
    setParseLoading(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  function downloadSampleCSV() {
    const csvContent = "data:text/csv;charset=utf-8,phone,name,course,city\n919876543210,John Doe,Full Stack Development,Chennai\n919988776655,Jane Smith,Data Science,Bangalore\n";
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "aira_sample_contacts.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  return (
    <div className="animate-slide-up bg-surface rounded-[2rem] p-8 shadow-lg ring-1 ring-[#c4c7c7]/20 min-h-[500px] flex flex-col">
      <StepIndicator current={currentStep} />

      {/* ── Step 1: Upload CSV ─────────────────────────────────────────── */}
      {currentStep === 1 && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start flex-1">
          {/* Left Column: Upload controls (7 cols) */}
          <div className="lg:col-span-7 space-y-6 flex flex-col justify-between h-full">
            <div>
              <h2 className="font-display text-2xl font-bold text-on-surface mb-1">Upload your contacts</h2>
              <p className="font-body text-sm text-on-surface-muted">Select a CSV or Excel file with contact data, or a photo/PDF scan of a notebook page — we will detect column mappings automatically.</p>
            </div>

            {(uploadError || parseError) && (
              <div className="text-sm font-semibold text-red-600 bg-red-50 border border-red-200 rounded-xl p-3 flex items-center gap-2">
                <X size={14} className="text-red-500 shrink-0" />
                <span className="truncate">{uploadError || parseError}</span>
              </div>
            )}

            <label
              className={cn(
                "relative flex flex-col items-center justify-center gap-5 py-12 rounded-2xl border-2 border-dashed cursor-pointer transition-all group",
                file ? "border-primary bg-primary/5" : "border-primary/30 hover:border-primary/70 hover:bg-primary/[0.04]",
                parseLoading && "pointer-events-none opacity-60"
              )}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
            >
              <div className={cn(
                "w-16 h-16 rounded-2xl flex items-center justify-center transition-all shadow-sm",
                file ? "bg-primary text-white" : "bg-primary/10 text-primary group-hover:bg-primary/20"
              )}>
                {parseLoading ? (
                  <Loader2 size={28} className="animate-spin text-primary" />
                ) : file ? (
                  <Check size={28} />
                ) : (
                  <CloudUpload size={28} />
                )}
              </div>
              <div className="text-center px-4">
                <p className="font-display text-lg font-bold text-on-surface truncate max-w-md mx-auto">
                  {parseLoading ? "Processing & parsing file..." : file ? file.name : "Drop your CSV, Excel, or scanned notebook photo here"}
                </p>
                <p className="font-body text-xs text-on-surface-muted mt-1.5">
                  {parseLoading
                    ? "Analyzing columns, verifying phone numbers, and searching for duplicates..."
                    : file
                    ? `${(file.size / 1024).toFixed(1)} KB${rowCount !== null ? ` · ${rowCount.toLocaleString()} rows` : ""} · click to change file`
                    : "or click to browse — .csv, .xlsx, .xls, .jpg, .png, .pdf · name and phone columns required"}
                </p>
              </div>
              {!file && !parseLoading && (
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[10px] text-on-surface-muted font-label border-t border-dashed border-primary/20 w-full justify-center pt-4 mt-1">
                  <span className="flex items-center gap-1"><Check size={10} className="text-primary" /> Auto-detects columns</span>
                  <span className="flex items-center gap-1"><Check size={10} className="text-primary" /> Deduplicates leads</span>
                  <span className="flex items-center gap-1"><Check size={10} className="text-primary" /> OCRs handwritten scans</span>
                </div>
              )}
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.jpg,.jpeg,.png,.pdf" className="hidden" onChange={handleFileSelect} disabled={parseLoading} />
            </label>

            <div className="flex justify-end">
              <button
                disabled={!file || parseLoading}
                onClick={() => setCurrentStep(2)}
                className={cn(
                  "flex items-center gap-2 px-6 py-3 rounded-xl font-label font-semibold text-sm transition-all",
                  file && !parseLoading
                    ? "bg-primary text-white hover:bg-primary/90 shadow-md"
                    : "bg-surface-mid text-on-surface-muted cursor-not-allowed"
                )}
              >
                Next <ChevronRight size={16} />
              </button>
            </div>
          </div>

          {/* Right Column: Template Guide (5 cols) */}
          <div className="lg:col-span-5 lg:border-l lg:border-surface-mid lg:pl-8 space-y-6">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-8 h-8 rounded-xl bg-primary-light flex items-center justify-center text-primary">
                <FileText size={16} />
              </div>
              <h3 className="font-display font-bold text-on-surface text-base">CSV Template</h3>
            </div>
            
            <div className="space-y-4">
              <p className="font-body text-xs text-on-surface-muted leading-relaxed">
                Make sure your CSV or Excel file includes these headers. Match additional variables with custom columns.
              </p>

              <div className="divide-y divide-surface-mid border-t border-b border-surface-mid">
                <div className="py-2 flex justify-between text-xs font-body">
                  <span className="font-mono text-on-surface font-semibold">phone</span>
                  <span className="text-red-700 font-bold bg-red-50 px-1.5 py-0.5 rounded text-[9px]">Required</span>
                </div>
                <div className="py-2 flex justify-between text-xs font-body">
                  <span className="font-mono text-on-surface font-semibold">name</span>
                  <span className="text-on-surface-muted bg-surface-low px-1.5 py-0.5 rounded text-[9px]">Optional</span>
                </div>
                <div className="py-2 flex justify-between text-xs font-body">
                  <span className="font-mono text-on-surface font-semibold">course / other</span>
                  <span className="text-on-surface-muted bg-surface-low px-1.5 py-0.5 rounded text-[9px]">Optional</span>
                </div>
              </div>

              <button
                onClick={downloadSampleCSV}
                className="w-full flex items-center justify-center gap-2 py-2.5 bg-surface-low hover:bg-surface-mid rounded-xl font-label text-xs font-bold text-on-surface transition-colors border border-surface-mid/60"
              >
                <Download size={13} />
                Download Sample CSV
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Step 2: Confirm & Upload ───────────────────────────────────── */}
      {currentStep === 2 && (
        <div className="space-y-6 flex-1">
          <div>
            <h2 className="font-display text-2xl font-bold text-on-surface mb-1">Review & Upload</h2>
            <p className="font-body text-sm text-on-surface-muted">Double-check the details below, then start the upload.</p>
          </div>

          {/* Summary Stats Grid */}
          {!uploadResult && !uploadError && parsedData && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-surface-low border border-surface-mid rounded-xl text-center shadow-sm">
                <p className="font-display text-2xl font-bold text-primary">{parsedData.total_rows.toLocaleString()}</p>
                <p className="font-label text-xs text-on-surface-muted mt-1">Total Contacts</p>
              </div>
              <div className={`p-4 rounded-xl text-center border shadow-sm ${parsedData.duplicate_count > 0 ? "bg-amber-50/70 border-amber-200" : "bg-surface-low border-surface-mid"}`}>
                <p className={`font-display text-2xl font-bold ${parsedData.duplicate_count > 0 ? "text-amber-700" : "text-on-surface-muted"}`}>{parsedData.duplicate_count}</p>
                <p className="font-label text-xs text-on-surface-muted mt-1">Duplicates (Skipped)</p>
              </div>
              <div className="p-4 bg-green-50/70 border border-green-200 rounded-xl text-center shadow-sm">
                <p className="font-display text-2xl font-bold text-green-700">{(parsedData.total_rows - parsedData.duplicate_count).toLocaleString()}</p>
                <p className="font-label text-xs text-on-surface-muted mt-1">New Leads</p>
              </div>
              <div className="md:col-span-3 p-4 bg-surface-low border border-surface-mid rounded-xl">
                <p className="font-label text-xs text-on-surface-muted mb-2 font-medium">Columns detected (auto-mapped phone/name columns highlighted)</p>
                <div className="flex flex-wrap gap-1.5">
                  {parsedData.columns.map(col => (
                    <span key={col} className={`px-2.5 py-1 rounded-md text-[10px] font-semibold tracking-wide border
                      ${col === "phone" || col === "name"
                        ? "bg-primary/10 text-primary border-primary/20 font-bold"
                        : "bg-surface-mid text-on-surface-muted border-transparent"}`}>
                      {col}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Fallback basic summary if parse endpoint was skipped or failed */}
          {!uploadResult && !uploadError && !parsedData && (
            <div className="rounded-2xl border border-surface-mid bg-surface-low p-6 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                  <FileText size={20} className="text-primary" />
                </div>
                <div>
                  <p className="font-label text-sm font-semibold text-on-surface">{file?.name ?? "No file"}</p>
                  <p className="font-body text-xs text-on-surface-muted">
                    {file ? `${(file.size / 1024).toFixed(1)} KB` : ""}
                    {rowCount !== null ? ` · ${rowCount.toLocaleString()} contacts` : ""}
                  </p>
                </div>
              </div>
              <div className="border-t border-surface-mid pt-4">
                <div>
                  <p className="font-label text-xs text-on-surface-muted mb-1">File Type</p>
                  <p className="font-label text-sm font-semibold text-on-surface">CSV</p>
                </div>
              </div>
            </div>
          )}

          {/* Data Preview Table */}
          {!uploadResult && !uploadError && parsedData && parsedData.preview.length > 0 && (
            <div className="space-y-2">
              <p className="font-label text-xs font-semibold text-on-surface-muted">Data Preview (First {parsedData.preview.length} rows)</p>
              <div className="overflow-x-auto rounded-xl ring-1 ring-[#c4c7c7]/20 bg-white max-h-[250px] shadow-sm">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="sticky top-0 z-20">
                    <tr className="bg-surface-low border-b border-surface-mid">
                      {parsedData.columns.map((col) => (
                        <th key={col} className="px-3.5 py-2.5 font-label font-bold text-on-surface-muted whitespace-nowrap bg-surface-low border-b border-surface-mid">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {parsedData.preview.map((row, ri) => (
                      <tr key={ri} className="border-b border-surface-mid/50 hover:bg-surface-low/50 transition-colors">
                        {parsedData.columns.map((col) => (
                          <td key={col} className="px-3.5 py-2.5 font-body text-on-surface whitespace-nowrap">
                            {row[col] ?? "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Success Banner */}
          {uploadResult && (
            <div className="rounded-2xl border-2 border-emerald-200 bg-emerald-50 p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-emerald-500 flex items-center justify-center">
                  <Check size={20} className="text-white" />
                </div>
                <div>
                  <p className="font-display text-lg font-bold text-emerald-800">Upload Successful</p>
                  <p className="font-body text-xs text-emerald-600">Batch ID: {uploadResult.batch_id}</p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-white/70 rounded-xl p-3 text-center">
                  <p className="font-display text-2xl font-bold text-emerald-700">{uploadResult.inserted}</p>
                  <p className="font-label text-xs text-emerald-600">Inserted</p>
                </div>
                <div className="bg-white/70 rounded-xl p-3 text-center">
                  <p className="font-display text-2xl font-bold text-amber-700">{uploadResult.duplicates}</p>
                  <p className="font-label text-xs text-amber-600">Duplicates</p>
                </div>
                <div className="bg-white/70 rounded-xl p-3 text-center">
                  <p className="font-display text-2xl font-bold text-blue-700">{uploadResult.assigned}</p>
                  <p className="font-label text-xs text-blue-600">Assigned</p>
                </div>
              </div>
            </div>
          )}

          {/* Error Banner */}
          {uploadError && (
            <div className="rounded-2xl border-2 border-red-200 bg-red-50 p-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-red-500 flex items-center justify-center">
                  <X size={20} className="text-white" />
                </div>
                <div>
                  <p className="font-display text-lg font-bold text-red-800">Upload Failed</p>
                  <p className="font-body text-sm text-red-600">{uploadError}</p>
                </div>
              </div>
            </div>
          )}

          <div className="flex justify-between">
            <button
              onClick={() => {
                if (uploadResult || uploadError) {
                  handleReset();
                } else {
                  setCurrentStep(1);
                }
              }}
              className="px-6 py-3 rounded-xl font-label font-semibold text-sm text-on-surface-muted hover:text-on-surface hover:bg-surface-low transition-all"
            >
              {uploadResult || uploadError ? "Start New Upload" : "Back"}
            </button>
            {!uploadResult && !uploadError && (
              <button
                disabled={!file || uploading}
                onClick={handleUpload}
                className={cn(
                  "flex items-center gap-2 px-6 py-3 rounded-xl font-label font-semibold text-sm transition-all",
                  !file || uploading
                    ? "bg-surface-mid text-on-surface-muted cursor-not-allowed"
                    : "bg-primary text-white hover:bg-primary/90 shadow-md"
                )}
              >
                {uploading ? (
                  <><Loader2 size={16} className="animate-spin" /> Uploading...</>
                ) : (
                  <><Upload size={16} /> Upload Contacts</>
                )}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// UPLOAD HISTORY TAB
// ═══════════════════════════════════════════════════════════════════════════════

function HistoryTab() {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const LIMIT = 20;

  const fetchHistory = useCallback(async (p: number) => {
    try {
      setHistoryLoading(true);
      const headers = await getAuthHeaders();
      const res = await fetch(
        `${API_URL}/api/v1/telecalling-upload/history?page=${p}&limit=${LIMIT}`,
        { headers }
      );
      if (!res.ok) throw new Error("Failed to load history");
      const raw = await res.json();
      const data: HistoryItem[] = Array.isArray(raw) ? raw : [];
      setHistory(data);
      setHasMore(data.length === LIMIT);
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory(page);
  }, [page, fetchHistory]);

  async function handleDownloadCsv(batchId: string, fileName: string) {
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(
        `${API_URL}/api/v1/telecalling-upload/history/${batchId}/csv`,
        { headers }
      );
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `assignments_${fileName}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      alert("Failed to download CSV.");
    }
  }

  return (
    <div className="animate-slide-up">
      <div className="bg-surface rounded-[2rem] p-8 shadow-lg ring-1 ring-[#c4c7c7]/20">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="font-display text-xl font-bold text-on-surface">Upload History</h2>
            <p className="font-body text-sm text-on-surface-muted mt-1">View all previous uploads and download assignment CSVs.</p>
          </div>
        </div>

        {historyLoading && history.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-on-surface-muted">
            <Loader2 size={24} className="animate-spin mr-3 text-primary" />
            <span className="font-body text-sm">Loading history...</span>
          </div>
        ) : history.length === 0 ? (
          <div className="text-center py-16">
            <div className="w-14 h-14 rounded-2xl bg-surface-low flex items-center justify-center mx-auto mb-3">
              <FileText size={24} className="text-on-surface-muted" />
            </div>
            <p className="font-label text-sm text-on-surface-muted">No uploads yet. Upload your first CSV to see it here.</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-surface-mid">
                    <th className="pb-3 pr-4 text-left font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">File Name</th>
                    <th className="pb-3 pr-4 text-left font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">Date</th>
                    <th className="pb-3 pr-4 text-right font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">Total</th>
                    <th className="pb-3 pr-4 text-right font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">Inserted</th>
                    <th className="pb-3 pr-4 text-right font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">Duplicates</th>
                    <th className="pb-3 pr-4 text-right font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">Assigned</th>
                    <th className="pb-3 font-label text-xs font-semibold text-on-surface-muted uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((item) => (
                    <tr key={item.id} className="border-b border-surface-mid/50 last:border-0 hover:bg-surface-low/50 transition-colors">
                      <td className="py-4 pr-4">
                        <div className="flex items-center gap-2">
                          <FileText size={14} className="shrink-0 text-on-surface-muted" />
                          <span className="truncate max-w-[200px] font-label text-sm font-medium text-on-surface">{item.file_name}</span>
                        </div>
                      </td>
                      <td className="py-4 pr-4 font-body text-sm text-on-surface-muted whitespace-nowrap">{formatDate(item.created_at)}</td>
                      <td className="py-4 pr-4 text-right font-label text-sm tabular-nums text-on-surface">{item.total_contacts}</td>
                      <td className="py-4 pr-4 text-right font-label text-sm tabular-nums text-emerald-600">{item.inserted}</td>
                      <td className="py-4 pr-4 text-right font-label text-sm tabular-nums text-amber-600">{item.duplicates}</td>
                      <td className="py-4 pr-4 text-right font-label text-sm tabular-nums text-blue-600">{item.assigned}</td>
                      <td className="py-4">
                        <button
                          onClick={() => handleDownloadCsv(item.id, item.file_name)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-label font-semibold text-primary hover:bg-primary/10 transition-colors"
                        >
                          <Download size={13} /> CSV
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-6 pt-4 border-t border-surface-mid">
              <span className="font-label text-xs text-on-surface-muted">Page {page}</span>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="px-4 py-2 rounded-xl font-label text-xs font-semibold border border-surface-mid text-on-surface-muted hover:bg-surface-low disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  Previous
                </button>
                <button
                  disabled={!hasMore}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-4 py-2 rounded-xl font-label text-xs font-semibold border border-surface-mid text-on-surface-muted hover:bg-surface-low disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCRIPTS TAB
// ═══════════════════════════════════════════════════════════════════════════════

function ScriptsTab() {
  const [scripts, setScripts] = useState<CallScript[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [showEditor, setShowEditor] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");

  const [formSteps, setFormSteps] = useState<FormStep[]>([emptyFormStep()]);
  const [simStepIdx, setSimStepIdx] = useState(0);

  const [previewScript, setPreviewScript] = useState<CallScript | null>(null);
  const [previewStep, setPreviewStep] = useState(0);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchScripts();
      setScripts(Array.isArray(data) ? data : []);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditingId(null);
    setFormName("");
    setFormSteps([emptyFormStep()]);
    setSimStepIdx(0);
    setShowEditor(true);
  }

  function openEdit(s: CallScript) {
    setEditingId(s.id);
    setFormName(s.name);
    setFormSteps(stepsToForm(s.steps));
    setSimStepIdx(0);
    setShowEditor(true);
  }

  function closeEditor() {
    setShowEditor(false);
    setEditingId(null);
    setSimStepIdx(0);
  }

  async function handleSave() {
    if (!formName.trim() || formSteps.every((s) => !s.text.trim())) return;
    setSaving(true);
    try {
      const steps = formToSteps(formSteps);
      if (editingId) {
        await apiUpdateScript(editingId, { name: formName.trim(), segment: null, steps, is_default: false });
      } else {
        await apiCreateScript({ name: formName.trim(), steps, is_default: false });
      }
      closeEditor();
      await load();
    } catch (err) {
      console.error("Failed to save script:", err);
    }
    setSaving(false);
  }

  async function handleToggleActive(s: CallScript) {
    try {
      await apiUpdateScript(s.id, { active: !s.active });
      setScripts((prev) => prev.map((x) => (x.id === s.id ? { ...x, active: !x.active } : x)));
    } catch { /* silent */ }
  }

  async function handleDelete(id: string) {
    try {
      await apiDeleteScript(id);
      setScripts((prev) => prev.filter((x) => x.id !== id));
      setDeletingId(null);
    } catch { /* silent */ }
  }

  function updateStep(idx: number, patch: Partial<FormStep>) {
    setFormSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  }

  function removeStep(idx: number) {
    setFormSteps((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  }

  function addBranch(stepIdx: number) {
    setFormSteps((prev) =>
      prev.map((s, i) => (i === stepIdx ? { ...s, branches: [...s.branches, { label: "", goto: 1 }] } : s))
    );
  }

  function updateBranch(stepIdx: number, branchIdx: number, patch: Partial<Branch>) {
    setFormSteps((prev) =>
      prev.map((s, i) =>
        i === stepIdx ? { ...s, branches: s.branches.map((b, bi) => (bi === branchIdx ? { ...b, ...patch } : b)) } : s
      )
    );
  }

  function removeBranch(stepIdx: number, branchIdx: number) {
    setFormSteps((prev) =>
      prev.map((s, i) => (i === stepIdx ? { ...s, branches: s.branches.filter((_, bi) => bi !== branchIdx) } : s))
    );
  }

  return (
    <div className="animate-slide-up">
      {/* Script list */}
      <div className="bg-surface rounded-[2rem] p-8 shadow-lg ring-1 ring-[#c4c7c7]/20">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="font-display text-xl font-bold text-on-surface">Call Scripts</h2>
            <p className="font-body text-sm text-on-surface-muted mt-1">Create guided talk tracks for your telecalling team.</p>
          </div>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 bg-primary text-white px-4 py-2.5 rounded-xl font-label text-sm font-semibold hover:bg-primary/90 shadow-md transition-all"
          >
            <Plus size={16} /> New Script
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={24} className="animate-spin text-primary" />
          </div>
        ) : scripts.length === 0 ? (
          <div className="text-center py-16">
            <div className="w-14 h-14 rounded-2xl bg-surface-low flex items-center justify-center mx-auto mb-3">
              <FileText size={24} className="text-on-surface-muted" />
            </div>
            <p className="font-label text-sm text-on-surface-muted">No scripts yet. Create one to give telecallers guided talk tracks.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {scripts.map((s) => (
              <div
                key={s.id}
                className="bg-surface-low border border-surface-mid rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:shadow-sm transition-all"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-display text-sm font-bold text-on-surface truncate">{s.name}</span>

                    {!s.active && (
                      <span className="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase bg-[#f1f5f9] text-[#94a3b8] border border-[#e2e8f0]">Inactive</span>
                    )}
                  </div>
                  <p className="font-body text-xs text-on-surface-muted mt-1">{s.steps.length} step{s.steps.length !== 1 ? "s" : ""}</p>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => handleToggleActive(s)} className="p-2 rounded-xl hover:bg-surface transition-colors">
                    {s.active ? <ToggleRight size={18} className="text-emerald-500" /> : <ToggleLeft size={18} className="text-on-surface-muted" />}
                  </button>
                  <button onClick={() => { setPreviewScript(s); setPreviewStep(0); }} className="p-2 rounded-xl hover:bg-surface text-on-surface-muted transition-colors">
                    <Eye size={15} />
                  </button>
                  <button onClick={() => openEdit(s)} className="p-2 rounded-xl hover:bg-surface text-on-surface-muted transition-colors">
                    <Pencil size={15} />
                  </button>
                  <button onClick={() => setDeletingId(s.id)} className="p-2 rounded-xl hover:bg-red-50 text-red-500 transition-colors">
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete confirmation */}
      {deletingId && (
        <Portal>
          <div className="fixed inset-0 z-dialog flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
            <div className="bg-surface rounded-2xl p-6 shadow-2xl w-full max-w-sm ring-1 ring-[#c4c7c7]/20">
              <h3 className="font-display text-base font-bold text-on-surface mb-2">Delete Script</h3>
              <p className="font-body text-sm text-on-surface-muted mb-6">Are you sure? This cannot be undone.</p>
              <div className="flex justify-end gap-3">
                <button onClick={() => setDeletingId(null)} className="px-4 py-2 rounded-xl font-label text-sm font-semibold text-on-surface-muted hover:bg-surface-low transition-colors">Cancel</button>
                <button onClick={() => handleDelete(deletingId)} className="bg-red-600 text-white px-4 py-2 rounded-xl font-label text-sm font-semibold hover:bg-red-700 transition-colors">Delete</button>
              </div>
            </div>
          </div>
        </Portal>
      )}

      {/* Create/Edit Modal (Full Screen Redesign) */}
      {showEditor && (() => {
        const safeSimStepIdx = Math.min(simStepIdx, Math.max(0, formSteps.length - 1));
        const currentSimStep = formSteps[safeSimStepIdx] || { text: "", note: "", branches: [] };
        return (
          <Portal>
            <div className="fixed inset-0 z-dialog bg-[#f8fafc] flex flex-col animate-fade-in overflow-hidden">
              {/* Full Screen Header */}
              <div className="bg-surface border-b border-surface-mid p-6 flex items-center justify-between shrink-0 shadow-sm">
                <div className="flex items-center gap-3">
                  <button 
                    onClick={closeEditor} 
                    className="p-2 rounded-xl hover:bg-surface-low text-on-surface-muted transition-colors flex items-center gap-1 font-label text-xs font-semibold"
                  >
                    <X size={16} /> Close
                  </button>
                  <div className="h-6 w-[1px] bg-surface-mid" />
                  <h2 className="font-display text-base font-bold text-on-surface">
                    {editingId ? "Edit Talk Track Script" : "Create New Talk Track Script"}
                  </h2>
                </div>
                <div className="flex items-center gap-3">
                  <button 
                    onClick={closeEditor} 
                    className="px-4 py-2.5 rounded-xl font-label text-xs font-semibold text-on-surface-muted hover:bg-surface-low transition-colors"
                  >
                    Cancel
                  </button>
                  <button 
                    onClick={handleSave} 
                    disabled={saving}
                    className="flex items-center gap-2 bg-primary text-white px-5 py-2.5 rounded-xl font-label text-xs font-semibold hover:bg-primary/90 shadow-md disabled:opacity-50 transition-all"
                  >
                    {saving && <Loader2 size={14} className="animate-spin" />}
                    {editingId ? "Save Changes" : "Save & Publish"}
                  </button>
                </div>
              </div>

              {/* Split-pane Editor Body */}
              <div className="flex-grow flex flex-col lg:flex-row overflow-hidden bg-[#f8fafc]">
                {/* Left Pane: Form Editor (60% width on large screens) */}
                <div className="w-full lg:w-[60%] flex flex-col h-full border-r border-surface-mid overflow-hidden">
                  <div className="flex-grow overflow-y-auto p-6 lg:p-8 space-y-6">
                    {/* Card 1: Script Title */}
                    <div className="bg-surface rounded-3xl p-6 shadow-sm border border-surface-mid">
                      <label className="block font-label text-xs font-bold text-on-surface-muted mb-2 uppercase tracking-wider">
                        Script Talk Track Name
                      </label>
                      <input 
                        type="text" 
                        value={formName} 
                        onChange={(e) => setFormName(e.target.value)} 
                        placeholder="e.g., Cold Calling Outbound Script - Batch A"
                        className="w-full border border-surface-mid rounded-2xl px-5 py-4 font-body text-sm text-on-surface bg-surface placeholder:text-on-surface-muted focus:outline-none focus:ring-2 focus:ring-primary transition-all" 
                      />
                      <p className="text-[11px] text-on-surface-muted mt-2">
                        Give your talk track a clear name so telecallers know when to select it.
                      </p>
                    </div>

                    {/* Card 2: Script Steps */}
                    <div className="bg-surface rounded-3xl p-6 shadow-sm border border-surface-mid space-y-6">
                      <div className="flex items-center justify-between border-b border-surface-mid pb-4">
                        <div>
                          <h3 className="font-display text-sm font-bold text-on-surface">Interactive Conversation Steps</h3>
                          <p className="font-body text-xs text-on-surface-muted mt-0.5">Define script lines, tips, and call flow routing choices.</p>
                        </div>
                        <button 
                          onClick={() => setFormSteps((prev) => [...prev, emptyFormStep()])}
                          className="flex items-center gap-1.5 bg-surface border border-surface-mid text-on-surface px-4 py-2 rounded-xl font-label text-xs font-semibold hover:bg-surface-low transition-colors"
                        >
                          <Plus size={14} /> Add New Step
                        </button>
                      </div>

                      <div className="space-y-6">
                        {formSteps.map((step, idx) => (
                          <div key={idx} className="bg-surface-low border border-surface-mid rounded-2xl p-5 relative hover:shadow-sm transition-all group">
                            <div className="flex items-center gap-2.5 mb-4 border-b border-surface-mid/50 pb-2">
                              <span className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-[10px] font-black shrink-0">
                                {idx + 1}
                              </span>
                              <span className="font-label text-xs font-bold text-on-surface uppercase tracking-wider">Step {idx + 1} details</span>
                              {formSteps.length > 1 && (
                                <button 
                                  onClick={() => {
                                    removeStep(idx);
                                    setSimStepIdx(0);
                                  }} 
                                  className="ml-auto p-1.5 rounded-lg hover:bg-red-50 text-on-surface-muted hover:text-red-500 transition-colors opacity-60 hover:opacity-100"
                                  title="Remove Step"
                                >
                                  <Trash2 size={14} />
                                </button>
                              )}
                            </div>

                            <div className="space-y-4">
                              <div>
                                <label className="block font-label text-[10px] font-bold text-on-surface-muted mb-1.5 uppercase tracking-wide">
                                  Telecaller Talk track line (What the caller says)
                                </label>
                                <textarea 
                                  value={step.text} 
                                  onChange={(e) => updateStep(idx, { text: e.target.value })} 
                                  placeholder="Hello, is this {{name}}? I'm calling from Anril..." 
                                  rows={3}
                                  className="w-full border border-surface-mid rounded-xl px-4 py-3 font-body text-sm text-on-surface bg-surface placeholder:text-on-surface-muted focus:outline-none focus:ring-2 focus:ring-primary resize-none transition-all" 
                                />
                              </div>

                              <div>
                                <label className="block font-label text-[10px] font-bold text-on-surface-muted mb-1.5 uppercase tracking-wide">
                                  Coaching / Hint note (Optional)
                                </label>
                                <input 
                                  type="text" 
                                  value={step.note} 
                                  onChange={(e) => updateStep(idx, { note: e.target.value })} 
                                  placeholder="e.g., Speak slowly and wait for their response."
                                  className="w-full border border-surface-mid rounded-xl px-4 py-2.5 font-body text-xs text-on-surface bg-surface placeholder:text-on-surface-muted focus:outline-none focus:ring-2 focus:ring-primary transition-all" 
                                />
                              </div>

                              {/* Interactive Branches */}
                              <div className="bg-surface rounded-xl p-4 border border-surface-mid">
                                <div className="flex items-center justify-between mb-3">
                                  <span className="font-label text-[10px] font-bold text-on-surface-muted uppercase flex items-center gap-1.5">
                                    <GitBranch size={12} className="text-primary" /> Conversation Paths &amp; Branches
                                  </span>
                                  <button 
                                    onClick={() => addBranch(idx)} 
                                    className="font-label text-[10px] font-bold text-primary hover:text-primary/80 flex items-center gap-1 transition-colors"
                                  >
                                    <Plus size={10} /> Add Branch Option
                                  </button>
                                </div>

                                {step.branches.length === 0 ? (
                                  <p className="text-[10px] text-on-surface-muted italic">
                                    No custom branches. The script will simply guide the caller to the next logical step.
                                  </p>
                                ) : (
                                  <div className="space-y-2.5">
                                    {step.branches.map((br, bi) => (
                                      <div key={bi} className="flex items-center gap-3 bg-surface-low p-2.5 rounded-lg border border-surface-mid">
                                        <div className="flex-1">
                                          <label className="block text-[8px] font-bold text-on-surface-muted uppercase mb-1">
                                            Button Label (e.g. &quot;Interested&quot; / &quot;Not Interested&quot;)
                                          </label>
                                          <input 
                                            type="text" 
                                            value={br.label} 
                                            onChange={(e) => updateBranch(idx, bi, { label: e.target.value })} 
                                            placeholder="e.g. Yes, tell me more"
                                            className="w-full border border-surface-mid rounded-md px-2 py-1 font-body text-xs bg-surface text-on-surface focus:outline-none focus:ring-1 focus:ring-primary" 
                                          />
                                        </div>
                                        <div className="w-24">
                                          <label className="block text-[8px] font-bold text-on-surface-muted uppercase mb-1">
                                            Go to Step
                                          </label>
                                          <Select
                                            size="sm"
                                            aria-label="Go to Step"
                                            value={String(br.goto)}
                                            onChange={(v) => updateBranch(idx, bi, { goto: parseInt(v) || 1 })}
                                            options={formSteps.map((_, sIdx) => ({ value: String(sIdx + 1), label: `Step ${sIdx + 1}` }))}
                                          />
                                        </div>
                                        <button 
                                          onClick={() => removeBranch(idx, bi)} 
                                          className="p-1.5 rounded-md hover:bg-red-50 text-on-surface-muted hover:text-red-500 transition-colors mt-4"
                                        >
                                          <X size={12} />
                                        </button>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="pt-4 border-t border-surface-mid flex justify-center">
                        <button 
                          onClick={() => setFormSteps((prev) => [...prev, emptyFormStep()])}
                          className="flex items-center gap-2 bg-primary/10 text-primary px-8 py-3.5 rounded-2xl font-label text-xs font-semibold hover:bg-primary/15 transition-all shadow-sm"
                        >
                          <Plus size={16} /> Add Next Script Step
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Right Pane: Cockpit Simulator (40% width on large screens) */}
                <div className="hidden lg:flex lg:w-[40%] flex-col h-full bg-[#f4f1eb] p-8 overflow-y-auto items-center justify-center relative select-none">
                  {/* Phone Bezel */}
                  <div className="w-full max-w-[340px] bg-white rounded-[40px] border-[8px] border-slate-900 shadow-2xl overflow-hidden flex flex-col relative aspect-[9/18] min-h-[580px] max-h-[640px]">
                    {/* Speaker Notch */}
                    <div className="absolute top-0 inset-x-0 h-6 flex justify-center items-center z-10">
                      <div className="w-24 h-4 bg-slate-900 rounded-b-xl" />
                    </div>

                    {/* Dialer Header */}
                    <div className="bg-slate-900 text-white pt-8 pb-5 px-5 flex flex-col items-center shrink-0">
                      <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center font-bold text-slate-300 text-sm mb-2 shadow-inner">
                        JD
                      </div>
                      <h4 className="font-display font-bold text-xs text-white">John Doe</h4>
                      <p className="font-body text-[9px] text-slate-400 mt-0.5">+1 (555) 019-2834</p>
                      
                      <div className="flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-2.5 py-0.5 rounded-full text-[9px] font-semibold mt-3 animate-pulse">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        Connected · 01:24
                      </div>
                    </div>

                    {/* Cockpit Screen Body */}
                    <div className="flex-grow p-4 space-y-4 overflow-y-auto bg-slate-50 flex flex-col justify-start">
                      {/* What you say speech bubble */}
                      <div className="bg-primary-50 border border-primary-100 rounded-2xl p-4 relative shadow-sm shrink-0">
                        <div className="text-[8px] font-bold text-primary-600 uppercase tracking-wider mb-1.5">
                          What you say:
                        </div>
                        <p className="font-body text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
                          {(() => {
                            const rawText = currentSimStep.text || "Hello! Is this John Doe?";
                            return rawText.replace(/\{\{\s*name\s*\}\}/gi, "John Doe");
                          })()}
                        </p>
                      </div>

                      {/* Coaching note */}
                      {currentSimStep.note && (
                        <div className="bg-amber-50 border border-amber-100 rounded-2xl p-3.5 shadow-sm flex items-start gap-2 shrink-0">
                          <span className="text-xs shrink-0 mt-0.5">💡</span>
                          <div>
                            <div className="text-[8px] font-bold text-amber-800 uppercase tracking-wider">
                              Coaching tip:
                            </div>
                            <p className="font-body text-[10px] text-amber-700 mt-0.5 leading-relaxed">
                              {currentSimStep.note}
                            </p>
                          </div>
                        </div>
                      )}

                      {/* Branches & Actions */}
                      <div className="mt-auto pt-4 space-y-2">
                        <div className="text-[8px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                          Responses &amp; Routing:
                        </div>
                        
                        {currentSimStep.branches && currentSimStep.branches.length > 0 ? (
                          <div className="space-y-1.5 max-h-[180px] overflow-y-auto pr-1">
                            {currentSimStep.branches.map((br, bi) => (
                              <button
                                key={bi}
                                onClick={() => {
                                  const targetStepIdx = br.goto - 1;
                                  if (targetStepIdx >= 0 && targetStepIdx < formSteps.length) {
                                    setSimStepIdx(targetStepIdx);
                                  }
                                }}
                                className="w-full bg-white hover:bg-slate-100 border border-slate-200 text-left px-3 py-2 rounded-xl font-body text-xs text-slate-700 hover:text-slate-900 transition-all flex items-center justify-between shadow-sm group"
                              >
                                <span className="truncate pr-2">{br.label || `Choice ${bi + 1}`}</span>
                                <span className="text-[9px] font-bold text-primary-600 flex items-center gap-0.5 shrink-0 group-hover:translate-x-0.5 transition-transform">
                                  Go to {br.goto} <ChevronRight size={10} />
                                </span>
                              </button>
                            ))}
                          </div>
                        ) : (
                          <div className="text-center py-4 bg-slate-100 border border-dashed border-slate-200 rounded-xl">
                            <p className="font-body text-[10px] text-slate-400 italic">
                              {formSteps.length > 1 && safeSimStepIdx < formSteps.length - 1 ? (
                                <span>No custom branches. Next step in sequence is Step {safeSimStepIdx + 2}.</span>
                              ) : (
                                <span>End of conversation script track.</span>
                              )}
                            </p>
                            {formSteps.length > 1 && safeSimStepIdx < formSteps.length - 1 && (
                              <button
                                onClick={() => setSimStepIdx(safeSimStepIdx + 1)}
                                className="mt-2 bg-primary hover:bg-primary/90 text-white text-[9px] font-semibold px-2.5 py-1 rounded-lg transition-colors inline-flex items-center gap-0.5 shadow-sm"
                              >
                                Next Step <ChevronRight size={10} />
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Bezel Footer info */}
                    <div className="bg-slate-900 py-3.5 px-4 border-t border-slate-800 flex items-center justify-between text-white shrink-0">
                      <span className="font-body text-[9px] text-slate-400">
                        Step {safeSimStepIdx + 1} of {formSteps.length}
                      </span>
                      <button
                        onClick={() => setSimStepIdx(0)}
                        className="flex items-center gap-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-[9px] font-semibold px-2.5 py-1.5 rounded-lg transition-colors border border-slate-700 shadow-inner"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="lucide lucide-rotate-ccw"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                        Reset Simulator
                      </button>
                    </div>
                  </div>

                  {/* Simulator background helper info */}
                  <div className="absolute bottom-4 text-center">
                    <p className="font-label text-[10px] font-bold text-on-surface-muted uppercase tracking-wider">
                      Live Telecalling Simulator
                    </p>
                    <p className="font-body text-[9px] text-on-surface-muted mt-0.5">
                      Edits on the left update the simulator track in real-time.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </Portal>
        );
      })()}

      {/* Preview Modal */}
      {previewScript && (
        <Portal>
          <div className="fixed inset-0 z-dialog flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
            <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-2xl ring-1 ring-[#c4c7c7]/20 max-h-[90vh] flex flex-col">
              <div className="flex items-center justify-between p-6 pb-4 border-b border-surface-mid shrink-0">
                <div>
                  <div className="flex items-center gap-2">
                    <Eye size={18} className="text-primary" />
                    <h2 className="font-display text-lg font-bold text-on-surface">Script Preview</h2>
                  </div>
                  <p className="font-body text-xs text-on-surface-muted mt-0.5">{previewScript.name}</p>
                </div>
                <button onClick={() => { setPreviewScript(null); setPreviewStep(0); }} className="p-2 rounded-xl hover:bg-surface-low text-on-surface-muted transition-colors"><X size={18} /></button>
              </div>
              <div className="flex-1 overflow-y-auto p-6 space-y-3">
                {previewScript.steps.sort((a, b) => a.order - b.order).map((step, idx) => {
                  const isCurrent = idx === previewStep;
                  return (
                    <div key={idx} className={cn(
                      "rounded-xl p-4 border-2 transition-all",
                      isCurrent ? "border-primary bg-primary/5 shadow-sm" : "border-surface-mid bg-surface"
                    )}>
                      <div className="flex items-start gap-3">
                        <span className={cn(
                          "shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold",
                          isCurrent ? "bg-primary text-white" : "bg-surface-low text-on-surface-muted"
                        )}>{step.order}</span>
                        <div className="min-w-0 flex-1">
                          <p className={cn("font-body text-sm", isCurrent ? "text-on-surface font-semibold" : "text-on-surface-muted")}>{step.text}</p>
                          {step.note && <p className="font-body text-xs text-on-surface-muted italic mt-1">{step.note}</p>}
                          {isCurrent && step.branches && step.branches.length > 0 && (
                            <div className="flex flex-wrap gap-2 mt-3">
                              {step.branches.map((br, bi) => (
                                <button key={bi} onClick={() => { const i = previewScript.steps.findIndex((s) => s.order === br.goto); if (i >= 0) setPreviewStep(i); }}
                                  className="bg-surface-low text-on-surface px-3 py-1.5 rounded-lg font-label text-xs font-semibold hover:bg-surface-mid flex items-center gap-1 transition-colors">
                                  <ChevronRight size={12} />{br.label || `Go to ${br.goto}`}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex items-center justify-between p-6 pt-4 border-t border-surface-mid shrink-0">
                <span className="font-label text-xs text-on-surface-muted">Step {previewStep + 1} of {previewScript.steps.length}</span>
                <div className="flex gap-2">
                  <button onClick={() => setPreviewStep((p) => Math.max(0, p - 1))} disabled={previewStep === 0}
                    className="px-4 py-2 rounded-xl font-label text-xs font-semibold text-on-surface-muted hover:bg-surface-low disabled:opacity-40 transition-colors">Back</button>
                  <button onClick={() => setPreviewStep((p) => Math.min(previewScript.steps.length - 1, p + 1))} disabled={previewStep === previewScript.steps.length - 1}
                    className="flex items-center gap-1 bg-primary text-white px-4 py-2 rounded-xl font-label text-sm font-semibold hover:bg-primary/90 disabled:opacity-40 transition-all">
                    Next<ChevronRight size={14} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </Portal>
      )}
    </div>
  );
}
