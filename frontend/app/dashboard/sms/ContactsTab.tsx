"use client";

import { useState } from "react";
import useSWR from "swr";
import { ClipboardPaste, Plus, Search, Upload } from "lucide-react";
import { toast } from "sonner";
import { ConfirmModal } from "@/components/ConfirmModal";
import { CheckTick } from "@/components/ui/controls";
import { api, type SmsContactGroup } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Pager } from "./CampaignDetail";
import { AddContactModal, PasteModal, UploadModal } from "./ContactModals";
import { GroupsPanel } from "./GroupsPanel";
import { formatCount, friendlyError } from "./helpers";
import { Badge, Btn, Card, CardHeader, Empty, Field, LoadError, Modal, Skeleton, TableWrap, inputCls, tdCls, thCls } from "./ui";
import { usePerm } from "./usePerm";

const PAGE = 50;
const API_CHUNK = 1000;

function chunks<T>(items: T[]): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += API_CHUNK) out.push(items.slice(i, i + API_CHUNK));
  return out;
}

export function ContactsTab() {
  const [sub, setSub] = useState<"contacts" | "groups">("contacts");
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Contacts" className="flex gap-2">
        {(["contacts", "groups"] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={sub === k}
            onClick={() => setSub(k)}
            className={cn(
              "h-9 rounded-full border px-4 text-sm font-bold",
              sub === k ? "border-primary bg-primary/5 text-primary" : "border-[#e2e8f0] text-[#64748b] hover:border-slate-300",
            )}
          >
            {k === "contacts" ? "Contacts" : "Groups"}
          </button>
        ))}
      </div>
      {sub === "contacts" ? <ContactsPanel /> : <GroupsPanel />}
    </div>
  );
}

type GroupAction = "add" | "remove";

function ContactsPanel() {
  const { canManage } = usePerm();
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [groupId, setGroupId] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [groupAction, setGroupAction] = useState<GroupAction | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const groups = useSWR("sms:contact-groups", () => api.sms.contactGroups(), { revalidateOnFocus: false });
  const contacts = useSWR(
    ["sms:contacts", query, groupId, offset],
    () => api.sms.contacts({ search: query || undefined, group_id: groupId || undefined, limit: PAGE, offset }),
    { keepPreviousData: true, revalidateOnFocus: false },
  );

  const groupList = groups.data?.groups ?? [];
  const groupName = new Map(groupList.map((g) => [g.id, g.name]));
  const rows = contacts.data?.items ?? [];
  const total = contacts.data?.total ?? 0;
  const allOnPage = rows.length > 0 && rows.every((c) => selected.has(c.id));
  const someOnPage = rows.some((c) => selected.has(c.id));

  function refresh() {
    void contacts.mutate();
    void groups.mutate();
  }

  function togglePage(on: boolean) {
    const next = new Set(selected);
    for (const c of rows) {
      if (on) next.add(c.id);
      else next.delete(c.id);
    }
    setSelected(next);
  }

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  async function removeSelected() {
    setDeleteBusy(true);
    try {
      let deleted = 0;
      for (const part of chunks(Array.from(selected))) deleted += (await api.sms.deleteContacts(part)).deleted;
      toast.success(`${formatCount(deleted)} contact(s) deleted.`);
      setSelected(new Set());
      setConfirmDelete(false);
      refresh();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't delete the contacts."));
      setConfirmDelete(false);
      refresh();
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Contacts"
        hint="People you can send SMS to without them being leads."
        action={
          canManage ? (
            <div className="flex flex-wrap gap-2">
              <Btn variant="outline" onClick={() => setAdding(true)}>
                <Plus size={15} /> Add contact
              </Btn>
              <Btn variant="outline" onClick={() => setPasting(true)}>
                <ClipboardPaste size={15} /> Paste numbers
              </Btn>
              <Btn onClick={() => setUploading(true)}>
                <Upload size={15} /> Add multiple contacts
              </Btn>
            </div>
          ) : undefined
        }
      />
      <form
        className="flex flex-wrap items-center gap-2 border-b border-[#f1f5f9] px-4 py-3 sm:px-5"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setQuery(searchInput.trim());
        }}
      >
        <div className="relative min-w-[200px] flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#64748b]" />
          <input aria-label="Search contacts" className={`${inputCls} pl-9`} placeholder="Search name or number" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        </div>
        <select
          aria-label="Filter by group"
          className={`${inputCls} w-auto`}
          value={groupId}
          onChange={(e) => {
            setGroupId(e.target.value);
            setOffset(0);
            setSelected(new Set());
          }}
        >
          <option value="">All contacts</option>
          {groupList.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({formatCount(g.contacts)})
            </option>
          ))}
        </select>
        <Btn type="submit" variant="outline">
          Search
        </Btn>
      </form>

      {canManage && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-[#f1f5f9] bg-[#f8fafc] px-4 py-2.5 sm:px-5">
          <span className="text-sm font-bold text-[#0A1528]">{formatCount(selected.size)} selected</span>
          <Btn variant="outline" className="h-8 text-xs" onClick={() => setGroupAction("add")}>
            Add contacts in group
          </Btn>
          <Btn variant="outline" className="h-8 text-xs" onClick={() => setGroupAction("remove")}>
            Remove from group
          </Btn>
          <Btn variant="danger" className="h-8 text-xs" onClick={() => setConfirmDelete(true)}>
            Delete
          </Btn>
          <Btn variant="link" className="text-xs" onClick={() => setSelected(new Set())}>
            Clear
          </Btn>
        </div>
      )}

      {contacts.isLoading && !contacts.data ? (
        <Skeleton className="m-4 h-48" />
      ) : contacts.error && !contacts.data ? (
        <LoadError message={friendlyError(contacts.error, "Check your connection.")} onRetry={() => void contacts.mutate()} />
      ) : rows.length === 0 ? (
        <Empty
          title={query || groupId ? "No contacts match." : "No contacts yet."}
          hint={query || groupId ? "Try a different search or group." : canManage ? "Add one, paste numbers, or upload a CSV or Excel file." : undefined}
        />
      ) : (
        <>
          <TableWrap>
            <table className="w-full min-w-[640px]">
              <thead>
                <tr className="border-b border-[#f1f5f9]">
                  {canManage && (
                    <th className={`${thCls} w-10`}>
                      <CheckTick checked={allOnPage} indeterminate={someOnPage && !allOnPage} onChange={togglePage} aria-label="Select everyone on this page" />
                    </th>
                  )}
                  <th className={thCls}>Number</th>
                  <th className={thCls}>Name</th>
                  <th className={thCls}>Groups</th>
                  <th className={thCls}>Consent</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="border-b border-[#f1f5f9] last:border-0">
                    {canManage && (
                      <td className={tdCls}>
                        <CheckTick checked={selected.has(c.id)} onChange={() => toggle(c.id)} aria-label={`Select ${c.name || c.phone}`} />
                      </td>
                    )}
                    <td className={`${tdCls} whitespace-nowrap font-semibold text-[#0A1528]`}>{c.phone}</td>
                    <td className={tdCls}>{c.name || "—"}</td>
                    <td className={tdCls}>
                      <div className="flex flex-wrap gap-1">
                        {c.group_ids.length === 0 ? (
                          <span className="text-[#94a3b8]">—</span>
                        ) : (
                          c.group_ids.map((id) => (
                            <Badge key={id} tone="info">
                              {groupName.get(id) ?? "Group"}
                            </Badge>
                          ))
                        )}
                      </div>
                    </td>
                    <td className={tdCls}>{c.promo_consent ? <Badge tone="success">Promo OK</Badge> : <span className="text-[#94a3b8]">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <Pager offset={offset} limit={PAGE} total={total} onOffset={setOffset} />
        </>
      )}

      <AddContactModal open={adding} groups={groupList} onClose={() => setAdding(false)} onDone={refresh} />
      <PasteModal open={pasting} groups={groupList} onClose={() => setPasting(false)} onDone={refresh} />
      <UploadModal open={uploading} groups={groupList} onClose={() => setUploading(false)} onDone={refresh} />
      <GroupActionModal
        action={groupAction}
        groups={groupList}
        defaultGroup={groupId}
        ids={Array.from(selected)}
        onClose={() => setGroupAction(null)}
        onDone={() => {
          setGroupAction(null);
          setSelected(new Set());
          refresh();
        }}
      />
      <ConfirmModal
        open={confirmDelete}
        onClose={() => !deleteBusy && setConfirmDelete(false)}
        onConfirm={() => void removeSelected()}
        title="Delete these contacts?"
        description={`${formatCount(selected.size)} contact(s) will be deleted from every group. Messages already sent stay in Reports.`}
        tone="danger"
        confirmLabel="Delete"
        loading={deleteBusy}
        loadingLabel="Deleting…"
      />
    </Card>
  );
}

function GroupActionModal({
  action,
  groups,
  defaultGroup,
  ids,
  onClose,
  onDone,
}: {
  action: GroupAction | null;
  groups: SmsContactGroup[];
  defaultGroup: string;
  ids: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const target = picked || (action === "remove" ? defaultGroup : "");

  async function run() {
    if (!action || !target) return;
    setBusy(true);
    try {
      let changed = 0;
      for (const part of chunks(ids)) {
        const res = action === "add" ? await api.sms.addContactsToGroup(target, part) : await api.sms.removeContactsFromGroup(target, part);
        changed += res.changed;
      }
      toast.success(action === "add" ? `${formatCount(changed)} contact(s) added to the group.` : `${formatCount(changed)} contact(s) removed from the group.`);
      setPicked("");
      onDone();
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't update the group."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={action !== null} title={action === "add" ? "Add to group" : "Remove from group"} onClose={() => !busy && onClose()}>
      <div className="space-y-3">
        {groups.length === 0 ? (
          <p className="text-sm text-[#64748b]">You have no groups yet. Create one in the Groups tab first.</p>
        ) : (
          <Field label="Group">
            <select className={inputCls} value={target} onChange={(e) => setPicked(e.target.value)}>
              <option value="">Choose a group…</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="flex justify-end gap-2">
          <Btn variant="outline" disabled={busy} onClick={onClose}>
            Cancel
          </Btn>
          <Btn busy={busy} disabled={!target} onClick={() => void run()}>
            {action === "add" ? "Add" : "Remove"}
          </Btn>
        </div>
      </div>
    </Modal>
  );
}
