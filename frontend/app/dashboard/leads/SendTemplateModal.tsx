"use client";
import { X } from "lucide-react";
import dynamic from "next/dynamic";

interface SendTemplateModalProps {
  leadId: string;
  onClose: () => void;
  onScheduleChange?: () => void;
}

// Dynamically import SendDetailsCard to avoid circular dependencies
const SendDetailsCard = dynamic(
  () => import("@/app/dashboard/telecalling/components/SendDetailsCard").then((mod) => mod.default),
  { ssr: false, loading: () => <div className="p-8 text-center text-xs text-[#64748b]">Loading...</div> }
);

// The one Send-template dialog (Segments and Conversations both render it), so it has one fixed
// size: the box does not grow or shrink as the template, blanks or Schedule picker change.
export function SendTemplateModal({ leadId, onClose, onScheduleChange }: SendTemplateModalProps) {
  return (
    <div className="fixed inset-0 z-dialog flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg h-[min(760px,calc(100dvh-2rem))] px-5 pt-5 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display text-lg font-bold text-[#0A1528]">Send template</h3>
          <button onClick={onClose} aria-label="Close" className="text-[#64748b] hover:text-[#0A1528]">
            <X size={20} />
          </button>
        </div>

        {/* The scrolling box has no bottom padding, so the pinned Send bar sits flush at its edge. */}
        <div className="pb-5">
          <SendDetailsCard leadId={leadId} explainUnavailable inDialog onScheduleChange={onScheduleChange} />
        </div>
      </div>
    </div>
  );
}
