"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { api, type SmsContactGroup, type SmsUploadPreview, type SmsUploadResult } from "@/lib/api";
import { formatCount, friendlyError, skippedRowsCsv } from "./helpers";
import { Btn, ConsentCheck, Field, FilePicker, InlinePanel, Notice, inputCls, saveCsv, textareaCls } from "./ui";

const NEW_GROUP = "__new__";

export interface GroupChoice { value: string; newName: string }
export const NO_GROUP: GroupChoice = { value: "", newName: "" };

/** Pick an existing group, no group, or type a new group's name. */
export function GroupSelect({ groups, choice, onChange, label = "Group" }: { groups: SmsContactGroup[]; choice: GroupChoice; onChange: (c: GroupChoice) => void; label?: string }) {
  return (
    <div className="space-y-2">
      <Field label={label}>
        <select className={inputCls} value={choice.value} onChange={(e) => onChange({ ...choice, value: e.target.value })}>
          <option value="">No group</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({formatCount(g.contacts)})
            </option>
          ))}
          <option value={NEW_GROUP}>New group…</option>
        </select>
      </Field>
      {choice.value === NEW_GROUP && (
        <Field label="New group name">
          <input className={inputCls} value={choice.newName} maxLength={80} onChange={(e) => onChange({ ...choice, newName: e.target.value })} />
        </Field>
      )}
    </div>
  );
}

export function choiceReady(c: GroupChoice): boolean {
  return c.value !== NEW_GROUP || c.newName.trim().length > 0;
}

/** Existing group id for the API; creates the group first when a new name was typed. */
async function resolveGroupId(c: GroupChoice): Promise<string | undefined> {
  if (c.value === NEW_GROUP) return (await api.sms.createContactGroup(c.newName.trim())).id;
  return c.value || undefined;
}

export function AddContactPanel({ open, groups, onClose, onDone }: { open: boolean; groups: SmsContactGroup[]; onClose: () => void; onDone: () => void }) {
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [group, setGroup] = useState<GroupChoice>(NO_GROUP);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const group_id = await resolveGroupId(group);
      await api.sms.addContact({ phone: phone.trim(), name: name.trim() || undefined, group_id, consent });
      toast.success("Contact added.");
      setPhone("");
      setName("");
      setConsent(false);
      onDone();
      onClose();
    } catch (err) {
      setError(friendlyError(err, "Couldn't add the contact."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <InlinePanel open={open} title="Add contact" onClose={() => !busy && onClose()}>
      <div className="space-y-3">
        <Field label="Mobile number" hint="10 digits, or with +91">
          <input className={inputCls} inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label="Name (optional)">
          <input className={inputCls} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        </Field>
        <GroupSelect groups={groups} choice={group} onChange={setGroup} />
        <ConsentCheck checked={consent} onChange={setConsent} />
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="flex justify-end gap-2">
          <Btn variant="outline" disabled={busy} onClick={onClose}>
            Cancel
          </Btn>
          <Btn busy={busy} disabled={!phone.trim() || !choiceReady(group)} onClick={() => void save()}>
            Add contact
          </Btn>
        </div>
      </div>
    </InlinePanel>
  );
}

function ResultSummary({ result }: { result: SmsUploadResult }) {
  return (
    <div className="space-y-3">
      <Notice tone="success">
        {formatCount(result.inserted)} added · {formatCount(result.updated)} updated · {formatCount(result.skipped_count)} skipped
      </Notice>
      {result.skipped_count > 0 && (
        <div className="space-y-1">
          <Btn variant="outline" className="h-9" onClick={() => saveCsv(skippedRowsCsv(result.skipped), "skipped_rows.csv")}>
            <Download size={14} /> Download skipped rows
          </Btn>
          {result.skipped_count > result.skipped.length && (
            <p className="text-xs text-[#64748b]">The file lists the first {formatCount(result.skipped.length)} skipped rows.</p>
          )}
        </div>
      )}
    </div>
  );
}

export function PastePanel({ open, groups, onClose, onDone }: { open: boolean; groups: SmsContactGroup[]; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const [group, setGroup] = useState<GroupChoice>(NO_GROUP);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SmsUploadResult | null>(null);

  function close() {
    setResult(null);
    setError(null);
    onClose();
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const group_id = await resolveGroupId(group);
      const res = await api.sms.pasteContacts({ text, group_id, consent });
      setResult(res);
      setText("");
      onDone();
    } catch (err) {
      setError(friendlyError(err, "Couldn't add these numbers."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <InlinePanel open={open} title="Paste numbers" onClose={() => !busy && close()}>
      {result ? (
        <div className="space-y-3">
          <ResultSummary result={result} />
          <div className="flex justify-end">
            <Btn onClick={close}>Done</Btn>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Numbers" hint='One per line: "number" or "number, name". Up to 5,000 lines.'>
            <textarea className={textareaCls} rows={7} value={text} placeholder={"9876543210\n9123456780, Asha"} onChange={(e) => setText(e.target.value)} />
          </Field>
          <GroupSelect groups={groups} choice={group} onChange={setGroup} />
          <ConsentCheck checked={consent} onChange={setConsent} />
          {error && <Notice tone="danger">{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Btn variant="outline" disabled={busy} onClick={close}>
              Cancel
            </Btn>
            <Btn busy={busy} disabled={!text.trim() || !choiceReady(group)} onClick={() => void save()}>
              Add numbers
            </Btn>
          </div>
        </div>
      )}
    </InlinePanel>
  );
}

export function UploadPanel({ open, groups, onClose, onDone }: { open: boolean; groups: SmsContactGroup[]; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SmsUploadPreview | null>(null);
  const [phoneCol, setPhoneCol] = useState("");
  const [nameCol, setNameCol] = useState("");
  const [group, setGroup] = useState<GroupChoice>(NO_GROUP);
  const [consent, setConsent] = useState(false);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SmsUploadResult | null>(null);

  function reset() {
    setFile(null);
    setPreview(null);
    setPhoneCol("");
    setNameCol("");
    setGroup(NO_GROUP);
    setConsent(false);
    setError(null);
    setResult(null);
  }

  function close() {
    reset();
    onClose();
  }

  async function pick(f: File | null) {
    setFile(f);
    setPreview(null);
    setError(null);
    if (!f) return;
    setReading(true);
    try {
      const p = await api.sms.previewContactUpload(f);
      setPreview(p);
      setPhoneCol(p.phone_column ?? "");
      setNameCol(p.name_column ?? "");
    } catch (err) {
      setError(friendlyError(err, "Couldn't read that file."));
    } finally {
      setReading(false);
    }
  }

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.sms.uploadContacts({
        file,
        group_id: group.value && group.value !== NEW_GROUP ? group.value : undefined,
        group_name: group.value === NEW_GROUP ? group.newName.trim() : undefined,
        phone_column: phoneCol || undefined,
        name_column: nameCol || undefined,
        consent,
      });
      setResult(res);
      onDone();
    } catch (err) {
      setError(friendlyError(err, "Couldn't upload the file."));
    } finally {
      setBusy(false);
    }
  }

  const sample = preview?.sample.slice(0, 5) ?? [];

  return (
    <InlinePanel open={open} title="Upload contacts" onClose={() => !busy && close()} wide>
      {result ? (
        <div className="space-y-3">
          <ResultSummary result={result} />
          <div className="flex justify-end">
            <Btn onClick={close}>Done</Btn>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <FilePicker label="CSV or Excel file" accept=".csv,.xlsx" file={file} onChange={(f) => void pick(f)} disabled={busy} hint="Up to 50,000 rows." />
          {reading && <p className="text-sm text-[#64748b]">Reading the file…</p>}
          {preview && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Number column">
                  <select className={inputCls} value={phoneCol} onChange={(e) => setPhoneCol(e.target.value)}>
                    <option value="">Choose…</option>
                    {preview.columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Name column">
                  <select className={inputCls} value={nameCol} onChange={(e) => setNameCol(e.target.value)}>
                    <option value="">None</option>
                    {preview.columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div>
                <p className="mb-1 text-xs font-bold text-[#334155]">
                  First {sample.length} row{sample.length === 1 ? "" : "s"} of {formatCount(preview.row_count)}
                </p>
                <div className="overflow-x-auto rounded-xl border border-[#e2e8f0]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#f1f5f9] bg-[#f8fafc]">
                        {preview.columns.map((c) => (
                          <th key={c} className="whitespace-nowrap px-3 py-2 text-left font-bold text-[#64748b]">
                            {c}
                            {c === phoneCol && <span className="ml-1 text-primary">(number)</span>}
                            {c === nameCol && <span className="ml-1 text-primary">(name)</span>}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sample.map((row, i) => (
                        <tr key={i} className="border-b border-[#f1f5f9] last:border-0">
                          {preview.columns.map((c, j) => (
                            <td key={c} className="max-w-[180px] truncate px-3 py-2 text-[#334155]">
                              {row[j] ?? ""}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <GroupSelect groups={groups} choice={group} onChange={setGroup} label="Add everyone to a group" />
              <ConsentCheck checked={consent} onChange={setConsent} />
            </>
          )}
          {error && <Notice tone="danger">{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Btn variant="outline" disabled={busy} onClick={close}>
              Cancel
            </Btn>
            <Btn busy={busy} disabled={!preview || !phoneCol || !choiceReady(group)} onClick={() => void upload()}>
              Upload
            </Btn>
          </div>
        </div>
      )}
    </InlinePanel>
  );
}
