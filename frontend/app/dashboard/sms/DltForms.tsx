"use client";

import { useState, type ReactNode } from "react";
import useSWR from "swr";
import { ChevronDown } from "lucide-react";
import { api, type SmsOk, type SmsTemplateType } from "@/lib/api";
import { friendlyError } from "./helpers";
import { Btn, Card, CardHeader, Field, Notice, inputCls, textareaCls } from "./ui";

function FormShell({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-[#e2e8f0]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-bold text-[#0A1528]"
      >
        {title}
        <ChevronDown size={16} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
      </button>
      {open && <div className="space-y-3 border-t border-[#f1f5f9] p-4">{children}</div>}
    </div>
  );
}

/** Runs a submit, shows the server's message on success, and a friendly error on failure. */
function useSubmit(run: () => Promise<SmsOk>, onDone?: () => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  async function submit() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await run();
      setMessage({ ok: res.ok !== false, text: res.message || "Done. It's now with the operator." });
      if (res.ok !== false) onDone?.();
    } catch (err) {
      setMessage({ ok: false, text: friendlyError(err, "That didn't go through.") });
    } finally {
      setBusy(false);
    }
  }
  return { busy, message, submit };
}

function Result({ message }: { message: { ok: boolean; text: string } | null }) {
  return message ? <Notice tone={message.ok ? "success" : "danger"}>{message.text}</Notice> : null;
}

const FILE_ACCEPT = ".jpg,.jpeg,.png,.gif,.pdf,.doc,.docx,.odt";
const MAX_FILE_MB = 20;

function AddEntity() {
  const [name, setName] = useState("");
  const [entityId, setEntityId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState("");
  const { busy, message, submit } = useSubmit(
    () => api.sms.addEntity({ entity_name: name.trim(), entity_id: entityId.trim(), files }),
    () => {
      setName("");
      setEntityId("");
      setFiles([]);
    },
  );
  function onFiles(list: FileList | null) {
    const picked = Array.from(list ?? []);
    if (picked.length > 5) return setFileError("Add 1 to 5 files.");
    if (picked.some((f) => f.size > MAX_FILE_MB * 1024 * 1024)) return setFileError(`Each file must be ${MAX_FILE_MB} MB or smaller.`);
    setFileError("");
    setFiles(picked);
  }
  return (
    <FormShell title="Add entity">
      <p className="text-xs text-[#64748b]">Your business as registered on DLT. Upload proof documents (1 to 5 files: jpg, png, gif, pdf, doc, docx, odt; {MAX_FILE_MB} MB each).</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Entity name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Entity ID (PE ID)">
          <input className={inputCls} value={entityId} onChange={(e) => setEntityId(e.target.value)} />
        </Field>
      </div>
      <Field label="Proof files">
        <input type="file" multiple accept={FILE_ACCEPT} className="block w-full text-sm" onChange={(e) => onFiles(e.target.files)} />
      </Field>
      {fileError && <p className="text-xs font-semibold text-danger">{fileError}</p>}
      <Result message={message} />
      <Btn busy={busy} disabled={!name.trim() || !entityId.trim() || files.length < 1 || !!fileError} onClick={() => void submit()}>
        Add entity
      </Btn>
    </FormShell>
  );
}

function AddSender() {
  const [entityId, setEntityId] = useState("");
  const [senderId, setSenderId] = useState("");
  const { busy, message, submit } = useSubmit(
    () => api.sms.addSender({ entity_id: entityId.trim(), sender_id: senderId.trim().toUpperCase() }),
    () => setSenderId(""),
  );
  const valid = senderId.trim().length >= 3 && senderId.trim().length <= 6;
  return (
    <FormShell title="Add sender ID">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Entity ID">
          <input className={inputCls} value={entityId} onChange={(e) => setEntityId(e.target.value)} />
        </Field>
        <Field label="Sender ID" hint="3 to 6 letters, like ANRILX">
          <input className={inputCls} value={senderId} maxLength={6} onChange={(e) => setSenderId(e.target.value)} />
        </Field>
      </div>
      <Result message={message} />
      <Btn busy={busy} disabled={!entityId.trim() || !valid} onClick={() => void submit()}>
        Add sender ID
      </Btn>
    </FormShell>
  );
}

function ExcelForm({ title, hint, withType, run }: { title: string; hint: string; withType?: boolean; run: (a: { entity_id: string; file: File; template_type: SmsTemplateType }) => Promise<SmsOk> }) {
  const [entityId, setEntityId] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const [file, setFile] = useState<File | null>(null);
  const { busy, message, submit } = useSubmit(
    () => run({ entity_id: entityId.trim(), file: file as File, template_type: type }),
    () => setFile(null),
  );
  return (
    <FormShell title={title}>
      <p className="text-xs text-[#64748b]">{hint}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Entity ID">
          <input className={inputCls} value={entityId} onChange={(e) => setEntityId(e.target.value)} />
        </Field>
        {withType && (
          <Field label="Type">
            <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as SmsTemplateType)}>
              <option value="service">Service</option>
              <option value="promotional">Promotional</option>
            </select>
          </Field>
        )}
      </div>
      <Field label="DLT Excel or CSV file">
        <input type="file" accept=".xlsx,.csv" className="block w-full text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Result message={message} />
      <Btn busy={busy} disabled={!entityId.trim() || !file} onClick={() => void submit()}>
        Upload
      </Btn>
    </FormShell>
  );
}

function AddTemplate({ onChanged }: { onChanged: () => void }) {
  const senders = useSWR("sms:senders", () => api.sms.senders(), { revalidateOnFocus: false });
  const [entityId, setEntityId] = useState("");
  const [senderIds, setSenderIds] = useState<string[]>([]);
  const [dltId, setDltId] = useState("");
  const [text, setText] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const { busy, message, submit } = useSubmit(
    () => api.sms.addTemplate({ entity_id: entityId.trim(), sender_ids: senderIds, dlt_template_id: dltId.trim(), message_text: text.trim(), template_type: type }),
    () => {
      setDltId("");
      setText("");
      onChanged();
    },
  );
  const list = senders.data?.senders ?? [];
  const forEntity = entityId.trim() ? list.filter((s) => s.entity_id === entityId.trim()) : list;
  return (
    <FormShell title="Add template">
      <p className="text-xs text-[#64748b]">Paste the wording exactly as approved on DLT. Use {"{#var#}"} where a value changes.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Entity ID">
          <input className={inputCls} list="sms-entity-ids" value={entityId} onChange={(e) => setEntityId(e.target.value)} />
          <datalist id="sms-entity-ids">
            {Array.from(new Set(list.map((s) => s.entity_id))).map((id) => (
              <option key={id} value={id} />
            ))}
          </datalist>
        </Field>
        <Field label="DLT template ID">
          <input className={inputCls} value={dltId} onChange={(e) => setDltId(e.target.value)} />
        </Field>
      </div>
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
      <Result message={message} />
      <Btn busy={busy} disabled={!entityId.trim() || !dltId.trim() || !text.trim() || senderIds.length === 0} onClick={() => void submit()}>
        Add template
      </Btn>
    </FormShell>
  );
}

export function DltForms({ onChanged }: { onChanged: () => void }) {
  return (
    <Card>
      <CardHeader title="Add to your DLT setup" hint="Only people with SMS manage access can use these." />
      <div className="space-y-3 p-4 sm:p-5">
        <AddEntity />
        <AddSender />
        <ExcelForm
          title="Add sender IDs from DLT Excel"
          hint="Upload the sender (header) export from your DLT portal."
          run={(a) => api.sms.addSenderExcel({ entity_id: a.entity_id, file: a.file }).then((r) => (onChanged(), r))}
        />
        <AddTemplate onChanged={onChanged} />
        <ExcelForm
          title="Add templates from DLT Excel"
          hint="Upload the template export from your DLT portal."
          withType
          run={(a) => api.sms.addTemplateExcel(a).then((r) => (onChanged(), r))}
        />
      </div>
    </Card>
  );
}
