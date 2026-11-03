"use client";

import { useState } from "react";
import { api, type SmsTemplateType } from "@/lib/api";
import { CheckField } from "@/components/ui/controls";
import { revalidateDlt } from "./DltForms";
import { isValidSenderId, parseSenderIds } from "./dltSetup";
import { friendlyError } from "./helpers";
import { Btn, Card, CardHeader, Field, Notice, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

const FILE_ACCEPT = ".jpg,.jpeg,.png,.gif,.pdf,.doc,.docx,.odt";
const MAX_FILE_MB = 20;

type Step = { ok: boolean; text: string };

export function AddEntityTab() {
  const { canManage } = usePerm();
  const [entityId, setEntityId] = useState("");
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState("");
  const [fileKey, setFileKey] = useState(0);
  const [withTemplate, setWithTemplate] = useState(false);
  const [senderText, setSenderText] = useState("");
  const [dltId, setDltId] = useState("");
  const [text, setText] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<{ entity?: Step; template?: Step }>({});

  const senderIds = parseSenderIds(senderText);
  const senderOk = senderIds.length > 0 && senderIds.every(isValidSenderId);
  const templateOk = !withTemplate || (senderOk && !!dltId.trim() && !!text.trim());
  const canSubmit = canManage && !!entityId.trim() && !!name.trim() && files.length >= 1 && !fileError && templateOk;

  function onFiles(list: FileList | null) {
    const picked = Array.from(list ?? []);
    if (picked.length > 5) return setFileError("Add 1 to 5 files.");
    if (picked.some((f) => f.size > MAX_FILE_MB * 1024 * 1024)) return setFileError(`Each file must be ${MAX_FILE_MB} MB or smaller.`);
    setFileError("");
    setFiles(picked);
  }

  async function submit() {
    if (busy || !canSubmit) return;
    setBusy(true);
    setResults({});
    let entityDone = false;
    try {
      const res = await api.sms.addEntity({ entity_name: name.trim(), entity_id: entityId.trim(), files });
      entityDone = res.ok !== false;
      setResults({ entity: { ok: entityDone, text: res.message || (entityDone ? "Entity submitted. It's now with the operator." : "The entity wasn't added.") } });
    } catch (err) {
      setResults({ entity: { ok: false, text: friendlyError(err, "The entity wasn't added.") } });
    }
    if (entityDone && withTemplate) {
      try {
        const res = await api.sms.addTemplate({
          entity_id: entityId.trim(),
          sender_ids: senderIds,
          dlt_template_id: dltId.trim(),
          message_text: text.trim(),
          template_type: type,
        });
        const ok = res.ok !== false;
        setResults((r) => ({ ...r, template: { ok, text: res.message || (ok ? "Template submitted." : "The template wasn't added.") } }));
      } catch (err) {
        setResults((r) => ({ ...r, template: { ok: false, text: friendlyError(err, "The template wasn't added.") } }));
      }
    }
    if (entityDone) {
      // The entity went through, so the form is cleared. A failed template is retried from DLT Manager > Content Template.
      setEntityId("");
      setName("");
      setFiles([]);
      setFileKey((k) => k + 1);
      setDltId("");
      setText("");
      setSenderText("");
      setWithTemplate(false);
      revalidateDlt();
    }
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader title="Add your DLT approved entity details" hint="Your business as registered on DLT. Our team checks it and links it to your account." />
      <div className="space-y-4 p-4 sm:p-5">
        {!canManage && <Notice tone="info">You can view this page. Ask an owner for SMS manage access to add an entity.</Notice>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Entity ID (PE ID)">
            <input className={inputCls} value={entityId} onChange={(e) => setEntityId(e.target.value)} disabled={!canManage} />
          </Field>
          <Field label="Entity name">
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} disabled={!canManage} />
          </Field>
        </div>
        <Field label="Proof files" hint={`1 to 5 files: jpg, png, gif, pdf, doc, docx, odt. ${MAX_FILE_MB} MB each.`}>
          <input key={fileKey} type="file" multiple accept={FILE_ACCEPT} disabled={!canManage} className="block w-full text-sm" onChange={(e) => onFiles(e.target.files)} />
        </Field>
        {fileError && <p className="text-xs font-semibold text-danger">{fileError}</p>}

        <CheckField checked={withTemplate} onChange={setWithTemplate} disabled={!canManage} label="Add content template (optional)" description="Send a template for this entity in the same step." />
        {withTemplate && (
          <div className="space-y-3 rounded-xl border border-[#e2e8f0] p-4">
            <Field label="Sender ID(s)" hint="3 to 6 letters each. Separate several with commas or spaces.">
              <input className={inputCls} value={senderText} onChange={(e) => setSenderText(e.target.value)} placeholder="ANRILX, ANRILY" />
            </Field>
            {senderText.trim() && !senderOk && <p className="text-xs font-semibold text-danger">Each sender ID must be 3 to 6 letters.</p>}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="DLT template ID">
                <input className={inputCls} value={dltId} onChange={(e) => setDltId(e.target.value)} />
              </Field>
              <Field label="Type">
                <select className={inputCls} value={type} onChange={(e) => setType(e.target.value as SmsTemplateType)}>
                  <option value="service">Service</option>
                  <option value="promotional">Promotional</option>
                </select>
              </Field>
            </div>
            <Field label="Message" hint="Exactly as approved on DLT. Use {#var#} where a value changes.">
              <textarea className={textareaCls} rows={3} value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
          </div>
        )}

        {results.entity && <Notice tone={results.entity.ok ? "success" : "danger"}>Entity: {results.entity.text}</Notice>}
        {results.template && <Notice tone={results.template.ok ? "success" : "danger"}>Template: {results.template.text}</Notice>}
        {results.template && !results.template.ok && (
          <p className="text-xs text-[#64748b]">The entity went through. Add the template again from DLT Manager &gt; Content Template.</p>
        )}

        <Btn busy={busy} disabled={!canSubmit} onClick={() => void submit()}>
          {withTemplate ? "Submit entity and template" : "Submit"}
        </Btn>
      </div>
    </Card>
  );
}
