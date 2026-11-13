"use client";

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Users, Search, Loader2 } from "lucide-react";
import { api, type Caller, type Lead } from "@/lib/api";
import { formatPhone } from "@/lib/utils";
import { CheckTick } from "@/components/ui/controls";
import { Select } from "@/components/ui/Select";
import { LEAD_STATUS_LABEL, TONE_CHIP, leadStatusTone } from "@/lib/call-wrapup";

interface BulkAssignmentProps {
  callers: Caller[];
}

export default function BulkAssignment({ callers }: BulkAssignmentProps) {
  const [leadList, setLeadList] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([]);
  const [bulkAssigneeId, setBulkAssigneeId] = useState<string>("");
  const [assigning, setAssigning] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.leads.list({ limit: 50 });
      setLeadList(res);
    } catch (err) {
      console.error("Failed to load leads for assignment:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filteredLeads = leadList.filter((l) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      (l.name && l.name.toLowerCase().includes(q)) ||
      (l.phone && l.phone.includes(q)) ||
      (l.segment && l.segment.toLowerCase().includes(q))
    );
  });

  const toggleSelectLead = (leadId: string) => {
    setSelectedLeadIds((prev) =>
      prev.includes(leadId) ? prev.filter((id) => id !== leadId) : [...prev, leadId]
    );
  };

  const toggleSelectAll = () => {
    const visibleIds = filteredLeads.map((l) => l.id);
    const allSelected = visibleIds.every((id) => selectedLeadIds.includes(id));
    if (allSelected) {
      setSelectedLeadIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
    } else {
      setSelectedLeadIds((prev) => Array.from(new Set([...prev, ...visibleIds])));
    }
  };

  const handleBulkAssign = async () => {
    if (selectedLeadIds.length === 0 || !bulkAssigneeId) return;
    setAssigning(true);
    try {
      const res = await api.leads.bulkAssign(selectedLeadIds, bulkAssigneeId);
      toast.success(`Successfully assigned ${res.updated || selectedLeadIds.length} leads`);
      setSelectedLeadIds([]);
      setBulkAssigneeId("");
      load();
    } catch (err) {
      console.error("Failed bulk assign:", err);
      toast.error("Failed to bulk assign leads");
    } finally {
      setAssigning(false);
    }
  };

  return (
    <div className="bg-surface rounded-card p-6 shadow-card ring-1 ring-[#c4c7c7]/15 flex flex-col">
      <h2 className="font-display text-base font-bold text-primary mb-1 flex items-center gap-2">
        <Users size={16} className="text-sky-600" /> Lead Bulk Assignment
      </h2>
      <p className="font-label text-xs text-on-surface-muted mb-4">Select multiple leads to dispatch or hand off to another agent queue.</p>

      <div className="flex items-center gap-2 bg-[#f8fafc] border border-[#e2e8f0] p-2 rounded-xl mb-4 text-xs">
        <Search size={14} className="text-[#94a3b8] shrink-0 ml-1" />
        <input
          type="text"
          placeholder="Search leads name, phone, segment..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="bg-transparent w-full focus:outline-none placeholder-[#94a3b8]"
        />
      </div>

      <div className="flex-1 overflow-y-auto max-h-[350px] border border-[#f1f5f9] rounded-2xl pr-1 mb-4">
        {loading ? (
          <div className="py-12 flex flex-col items-center justify-center">
            <Loader2 className="animate-spin text-[#94a3b8]" size={20} />
          </div>
        ) : filteredLeads.length === 0 ? (
          <p className="text-xs text-[#94a3b8] text-center py-12">No leads matching search query.</p>
        ) : (
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[#f1f5f9] bg-[#f8fafc]/50 sticky top-0 font-label text-[10px] text-[#94a3b8] uppercase font-bold">
                <th className="py-2.5 px-3 w-8">
                  <CheckTick
                    checked={filteredLeads.length > 0 && filteredLeads.every((l) => selectedLeadIds.includes(l.id))}
                    indeterminate={
                      selectedLeadIds.length > 0 &&
                      !filteredLeads.every((l) => selectedLeadIds.includes(l.id))
                    }
                    onChange={() => toggleSelectAll()}
                    size="sm"
                    aria-label="Select all leads"
                  />
                </th>
                <th className="py-2.5 px-2">Lead</th>
                <th className="py-2.5 px-2">Phone</th>
                <th className="py-2.5 px-2">Seg</th>
                <th className="py-2.5 px-2">Status</th>
                <th className="py-2.5 px-2">Assigned To</th>
              </tr>
            </thead>
            <tbody>
              {filteredLeads.map((lead) => {
                const isSelected = selectedLeadIds.includes(lead.id);
                const assignedCaller = callers.find((c) => c.id === lead.assigned_to);
                return (
                  <tr key={lead.id} className="border-b border-[#f1f5f9] hover:bg-[#f8fafc]/20 transition-colors">
                    <td className="py-2 px-3">
                      <CheckTick
                        checked={isSelected}
                        onChange={() => toggleSelectLead(lead.id)}
                        size="sm"
                        aria-label={`Select ${lead.name || "lead"}`}
                      />
                    </td>
                    <td className="py-2 px-2 font-bold text-[#13284A]">{lead.name || "Unnamed"}</td>
                    <td className="py-2 px-2 text-[#475569] font-medium">{formatPhone(lead.phone)}</td>
                    <td className="py-2 px-2">
                      <span className="bg-[#f1f5f9] px-1 py-0.5 rounded font-black text-[9px] uppercase">{lead.segment || "—"}</span>
                    </td>
                    <td className="py-2 px-2">
                      <span className={`px-1.5 py-0.5 rounded border font-label text-[9px] font-black uppercase ${TONE_CHIP[leadStatusTone(lead.call_status ?? "new")]}`}>
                        {LEAD_STATUS_LABEL[lead.call_status ?? "new"]}
                        {lead.do_not_call ? " (DNC)" : ""}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-[#475569] font-semibold truncate">
                      {assignedCaller ? assignedCaller.name : <span className="text-amber-500">Unassigned</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="flex items-center gap-3 bg-[#f8fafc] p-4 rounded-2xl border border-[#e2e8f0] mt-auto">
        <div className="flex-1">
          <span className="font-label text-[10px] text-[#94a3b8] uppercase font-extrabold block">Reassign To:</span>
          <Select
            size="sm"
            className="mt-1"
            aria-label="Reassign to"
            value={bulkAssigneeId}
            onChange={setBulkAssigneeId}
            placeholder="Select Caller..."
            options={callers.map((c) => ({ value: c.id, label: c.name }))}
          />
        </div>
        <div className="shrink-0 pt-4">
          <button
            onClick={handleBulkAssign}
            disabled={assigning || selectedLeadIds.length === 0 || !bulkAssigneeId}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl hover:bg-primary/95 disabled:opacity-50 font-label text-xs font-bold transition-all shadow-sm"
          >
            {assigning ? <Loader2 className="animate-spin" size={12} /> : null}
            Assign ({selectedLeadIds.length})
          </button>
        </div>
      </div>
    </div>
  );
}
