"use client";

import { useState, type ReactNode } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import { Search } from "lucide-react";
import { toast } from "sonner";
import { api, type SmsDltStatus, type SmsOk, type SmsTemplateType } from "@/lib/api";
import { isValidSenderId } from "./dltSetup";
import { friendlyError } from "./helpers";
import { Badge, Btn, Field, FilePicker, Modal, Notice, inputCls, textareaCls } from "./ui";

export const DLT_LIST_KEY = "sms:dlt-list";
export const TEMPLATES_KEY = "sms:templates";

/** Entities and senders the DLT Manager shows (shared by every tab on the Setup page). */
/** Pass enabled=false before the Bulk9 key is set: the list needs Bulk9 and would only return 409. */
export function useDltList(enabled = true) {
  return useSWR(enabled ? DLT_LIST_KEY : null, () => api.sms.dltList(), { revalidateOnFocus: false });
}

/** Refresh every list that a DLT change can affect. */
export function revalidateDlt() {
  void globalMutate(DLT_LIST_KEY);
  void globalMutate(TEMPLATES_KEY);
}

export function DltStatusBadge({ status }: { status: SmsDltStatus }) {
  return <Badge tone={status === "approved" ? "success" : "warn"}>{status === "approved" ? "Approved" : "Submitted"}</Badge>;
}

/** Search box + status filter + action buttons, shared by the three DLT Manager tables. */
export function ListToolbar({
  query,
  onQuery,
  placeholder,
  status,
  onStatus,
  options,
  children,
}: {
  query: string;
  onQuery: (v: string) => void;
  placeholder: string;
  status: string;
  onStatus: (v: string) => void;
  options: { value: string; label: string }[];
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#94a3b8]" />
        <input aria-label={placeholder} className={`${inputCls} pl-8`} placeholder={placeholder} value={query} onChange={(e) => onQuery(e.target.value)} />
      </div>
      <select aria-label="Filter by status" className={`${inputCls} w-auto`} value={status} onChange={(e) => onStatus(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {children && <div className="flex flex-wrap items-center gap-2 sm:ml-auto">{children}</div>}
    </div>
  );
}

/** Runs a submit; on success toasts the server's message and closes, on failure shows it in the form. */
function useModalSubmit(run: () => Promise<SmsOk>, onClose: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await run();
      if (res.ok === false) {
        setError(res.message || "That didn't go through.");
        return;
      }
      toast.success(res.message || "Done. It's now with the operator.");
      revalidateDlt();
      onClose();
    } catch (err) {
      setError(friendlyError(err, "That didn't go through."));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, submit };
}

function ErrorLine({ text }: { text: string }) {
  return text ? <Notice tone="danger">{text}</Notice> : null;
}

function EntityInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data } = useDltList();
  return (
    <Field label="Entity ID">
      <input className={inputCls} list="sms-dlt-entity-ids" value={value} onChange={(e) => onChange(e.target.value)} />
      <datalist id="sms-dlt-entity-ids">
        {(data?.entities ?? []).map((e) => (
          <option key={e.entity_id} value={e.entity_id}>
            {e.entity_name ?? ""}
          </option>
        ))}
      </datalist>
    </Field>
  );
}

function AddSenderForm({ onClose }: { onClose: () => void }) {
  const [entityId, setEntityId] = useState("");
  const [senderId, setSenderId] = useState("");
  const { busy, error, submit } = useModalSubmit(
    () => api.sms.addSender({ entity_id: entityId.trim(), sender_id: senderId.trim().toUpperCase() }),
    onClose,
  );
  return (
    <div className="space-y-3">
      <EntityInput value={entityId} onChange={setEntityId} />
      <Field label="Sender ID" hint="3 to 6 letters, like ANRILX">
        <input className={inputCls} value={senderId} maxLength={6} onChange={(e) => setSenderId(e.target.value)} />
      </Field>
      <ErrorLine text={error} />
      <Btn busy={busy} disabled={!entityId.trim() || !isValidSenderId(senderId.trim())} onClick={() => void submit()}>
        Add sender ID
      </Btn>
    </div>
  );
}

export function AddSenderPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Add sender ID" onClose={onClose}>
      <AddSenderForm onClose={onClose} />
    </Modal>
  );
}

function ExcelForm({
  hint,
  withType,
  run,
  onClose,
}: {
  hint: string;
  withType?: boolean;
  run: (a: { entity_id: string; file: File; template_type: SmsTemplateType }) => Promise<SmsOk>;
  onClose: () => void;
}) {
  const [entityId, setEntityId] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const [file, setFile] = useState<File | null>(null);
  const { busy, error, submit } = useModalSubmit(() => run({ entity_id: entityId.trim(), file: file as File, template_type: type }), onClose);
  return (
    <div className="space-y-3">
      <p className="text-xs text-[#64748b]">{hint}</p>
      <EntityInput value={entityId} onChange={setEntityId} />
      {withType && (
        <Field label="Type">
          <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as SmsTemplateType)}>
            <option value="service">Service</option>
            <option value="promotional">Promotional</option>
          </select>
        </Field>
      )}
      <FilePicker label="DLT Excel or CSV file" accept=".xlsx,.csv" file={file} onChange={setFile} disabled={busy} />
      <ErrorLine text={error} />
      <Btn busy={busy} disabled={!entityId.trim() || !file} onClick={() => void submit()}>
        Upload
      </Btn>
    </div>
  );
}

export function SenderExcelPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Import sender IDs from DLT Excel" onClose={onClose}>
      <ExcelForm
        hint="Upload the sender (header) export from your DLT portal."
        run={(a) => api.sms.addSenderExcel({ entity_id: a.entity_id, file: a.file })}
        onClose={onClose}
      />
    </Modal>
  );
}

export function TemplateExcelPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Import templates from DLT Excel" onClose={onClose}>
      <ExcelForm hint="Upload the template export from your DLT portal." withType run={(a) => api.sms.addTemplateExcel(a)} onClose={onClose} />
    </Modal>
  );
}

function AddTemplateForm({ onClose }: { onClose: () => void }) {
  const { data } = useDltList();
  const [entityId, setEntityId] = useState("");
  const [senderIds, setSenderIds] = useState<string[]>([]);
  const [dltId, setDltId] = useState("");
  const [text, setText] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const { busy, error, submit } = useModalSubmit(
    () => api.sms.addTemplate({ entity_id: entityId.trim(), sender_ids: senderIds, dlt_template_id: dltId.trim(), message_text: text.trim(), template_type: type }),
    onClose,
  );
  const list = data?.senders ?? [];
  const forEntity = entityId.trim() ? list.filter((s) => s.entity_id === entityId.trim()) : list;
  return (
    <div className="space-y-3">
      <p className="text-xs text-[#64748b]">Paste the wording exactly as approved on DLT. Use {"{#var#}"} where a value changes.</p>
      <EntityInput value={entityId} onChange={setEntityId} />
      <Field label="DLT template ID">
        <input className={inputCls} value={dltId} onChange={(e) => setDltId(e.target.value)} />
      </Field>
      <Field label="Sender IDs">
        {forEntity.length === 0 ? (
          <p className="text-xs text-[#64748b]">No sender IDs found yet. Add one first.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {forEntity.map((s) => {
              const on = senderIds.includes(s.sender_id);
              return (
                <button
                  key={`${s.entity_id}-${s.sender_id}`}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setSenderIds((cur) => (on ? cur.filter((x) => x !== s.sender_id) : [...cur, s.sender_id]))}
                  className={`h-8 rounded-lg border px-3 text-xs font-bold ${on ? "border-primary bg-primary/5 text-primary" : "border-[#e2e8f0] text-[#64748b]"}`}
                >
                  {s.sender_id}
                </button>
              );
            })}
          </div>
        )}
      </Field>
      <Field label="Template wording">
        <textarea className={textareaCls} rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <Field label="Type">
        <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as SmsTemplateType)}>
          <option value="service">Service</option>
          <option value="promotional">Promotional</option>
        </select>
      </Field>
      <ErrorLine text={error} />
      <Btn busy={busy} disabled={!entityId.trim() || !dltId.trim() || !text.trim() || senderIds.length === 0} onClick={() => void submit()}>
        Add template
      </Btn>
    </div>
  );
}

export function AddTemplatePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Add template" onClose={onClose} wide>
      <AddTemplateForm onClose={onClose} />
    </Modal>
  );
}
