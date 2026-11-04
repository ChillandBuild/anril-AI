"use client";

import { useState } from "react";
import { toast } from "sonner";
import { api, type SmsTemplateType } from "@/lib/api";
import { CheckField } from "@/components/ui/controls";
import { revalidateDlt } from "./DltForms";
import { isValidSenderId, parseSenderIds } from "./dltSetup";
import { ENTITY_ID_MESSAGE, friendlyError, isValidEntityId } from "./helpers";
import { Btn, Field, Modal, Notice, inputCls, textareaCls } from "./ui";
import { usePerm } from "./usePerm";

type Step = { ok: boolean; text: string };

function AddEntityForm({ onClose }: { onClose: () => void }) {
  const { canManage } = usePerm();
  const [entityId, setEntityId] = useState("");
  const [name, setName] = useState("");
  const [withTemplate, setWithTemplate] = useState(false);
  const [senderText, setSenderText] = useState("");
  const [dltId, setDltId] = useState("");
  const [text, setText] = useState("");
  const [type, setType] = useState<SmsTemplateType>("service");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<{ entity?: Step }>({});

  const senderIds = parseSenderIds(senderText);
  const senderOk = senderIds.length > 0 && senderIds.every(isValidSenderId);
  const templateOk = !withTemplate || (senderOk && !!dltId.trim() && !!text.trim());
  const entityIdOk = isValidEntityId(entityId);
  const canSubmit = canManage && entityIdOk && !!name.trim() && templateOk;

  async function submit() {
    if (busy || !canSubmit) return;
    setBusy(true);
    setResults({});
    let entityDone = false;
    let entityText = "";
    try {
      const res = await api.sms.addEntity({ entity_name: name.trim(), entity_id: entityId.trim() });
      entityDone = res.ok !== false;
      entityText = res.message || (entityDone ? "Entity submitted. It's now with the operator." : "The entity wasn't added.");
      setResults({ entity: { ok: entityDone, text: entityText } });
    } catch (err) {
      setResults({ entity: { ok: false, text: friendlyError(err, "The entity wasn't added.") } });
    }
    if (!entityDone) {
      setBusy(false);
      return;
    }
    // The entity went through: refresh the lists and close. Only a failed template keeps the news on screen (as a toast).
    let templateError = "";
    if (withTemplate) {
      try {
        const res = await api.sms.addTemplate({
          entity_id: entityId.trim(),
          sender_ids: senderIds,
          dlt_template_id: dltId.trim(),
          message_text: text.trim(),
          template_type: type,
        });
        if (res.ok === false) templateError = res.message || "The template wasn't added.";
      } catch (err) {
        templateError = friendlyError(err, "The template wasn't added.");
      }
    }
    revalidateDlt();
    if (templateError) {
      toast.error(`Entity added, but the template wasn't: ${templateError} Add it again from Content Template.`);
    } else {
      toast.success(withTemplate ? "Entity and template submitted. They're now with the operator." : entityText);
    }
    setBusy(false);
    onClose();
  }

  return (
    <>
      <div className="space-y-4">
        <p className="text-xs text-[#64748b]">Your business as registered on DLT. Our team checks it and links it to your account.</p>
        {!canManage && <Notice tone="info">You can view this page. Ask an owner for SMS manage access to add an entity.</Notice>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Entity ID (PE ID)">
            <input className={inputCls} value={entityId} onChange={(e) => setEntityId(e.target.value)} disabled={!canManage} inputMode="numeric" />
            {entityId.trim() && !entityIdOk && <span className="mt-1 block text-xs font-semibold text-danger">{ENTITY_ID_MESSAGE}</span>}
          </Field>
          <Field label="Entity name">
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} disabled={!canManage} />
          </Field>
        </div>

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

        {results.entity && !results.entity.ok && <Notice tone="danger">Entity: {results.entity.text}</Notice>}

        <Btn busy={busy} disabled={!canSubmit} onClick={() => void submit()}>
          {withTemplate ? "Submit entity and template" : "Submit"}
        </Btn>
      </div>
    </>
  );
}

/** "+ Add entity" popup (DLT Manager > Entity ID). Closes itself after a successful submit. */
export function AddEntityPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} title="Add entity" onClose={onClose} wide>
      <AddEntityForm onClose={onClose} />
    </Modal>
  );
}
