import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import type { Template, UsageEntry } from "../types";
import { STAFF_ALERT_WARNING, isStaffAlertMarketing, statusNote, usedInText } from "../template-filters";

type Props = {
  template: Template;
  /** Where it is used; undefined while the usage call is still loading or failed. */
  usage: UsageEntry[] | undefined;
  usageReady: boolean;
  /** Show "Fix and send again ›" only to people who may edit. */
  canFix: boolean;
  className?: string;
};

/** The three lines under a template: where it is used, why it isn't working, and the staff-alert warning. */
export default function TemplateNotes({ template: t, usage, usageReady, canFix, className = "" }: Props) {
  const note = statusNote(t);
  const warn = isStaffAlertMarketing(t, usage);
  return (
    <div className={`space-y-1.5 ${className}`}>
      {usageReady && <p className="text-xs text-ink-secondary">{usedInText(usage)}</p>}
      {note && (
        <p className="text-xs text-red-700">
          {note.text}
          {note.fixHref && canFix && (
            <>
              {" "}
              <Link
                href={note.fixHref}
                onClick={(e) => e.stopPropagation()}
                className="font-semibold underline underline-offset-2 hover:text-red-800"
              >
                Fix and send again ›
              </Link>
            </>
          )}
        </p>
      )}
      {warn && (
        <p className="flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{STAFF_ALERT_WARNING}</span>
        </p>
      )}
    </div>
  );
}
