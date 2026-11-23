"use client";
import { useState } from "react";
import useSWR from "swr";
import { GraduationCap, Pencil, Plus } from "lucide-react";
import { coursesApi, type Batch, type Course } from "@/lib/coursesApi";
import { useAuthRole } from "@/app/dashboard/contexts/AuthRoleContext";
import { BTN_PRIMARY, BTN_SECONDARY, Notice, errorText } from "@/app/dashboard/bookings/bookingsUi";
import { CatalogueTabs } from "../CatalogueTabs";
import { BatchPanel } from "./BatchPanel";
import { BatchSheet, CourseSheet } from "./CourseForms";
import { FeeRemindersCard } from "./FeeRemindersCard";
import { dayText, modeLabel, rupees, seatsText } from "./coursesLogic";

const STATUS_CLS = { open: "bg-emerald-50 text-emerald-800", full: "bg-amber-50 text-amber-900", closed: "bg-slate-100 text-slate-700" } as const;

export default function CoursesPage() {
  const { role, permissions } = useAuthRole();
  const owner = role === "owner";
  const can = (p: string) => owner || permissions.includes(p);
  const { data, error, mutate, isLoading } = useSWR("courses/list", coursesApi.list, { revalidateOnFocus: false });
  const [courseSheet, setCourseSheet] = useState<{ course: Course | null } | null>(null);
  const [batchSheet, setBatchSheet] = useState<{ course: Course; batch: Batch | null } | null>(null);
  const [open, setOpen] = useState<{ course: Course; batch: Batch } | null>(null);
  const [note, setNote] = useState("");

  const canManage = can("catalog.manage");
  const money = Boolean(data?.can_see_money);
  const reload = () => { setCourseSheet(null); setBatchSheet(null); void mutate(); };

  async function demoClass() {
    setNote("");
    try {
      const r = await coursesApi.setupDemoClass();
      setNote(r.has_staff === false
        ? "The free demo class is ready. Add a staff member to it in Bookings so parents can pick a time."
        : "The free demo class is ready. Parents can book it from your booking link.");
    } catch (e) {
      setNote(errorText(e, "Could not set up the demo class."));
    }
  }

  return (
    <div className="space-y-4">
      <CatalogueTabs />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-extrabold text-ink"><GraduationCap size={20} aria-hidden /> Courses and batches</h1>
          <p className="text-sm text-ink-secondary">Each course has batches. Parents see the next batch with seats left.</p>
        </div>
        {canManage ? (
          <div className="flex flex-wrap gap-2">
            {can("bookings.manage") ? <button type="button" className={BTN_SECONDARY} onClick={demoClass}>Set up free demo class</button> : null}
            <button type="button" className={BTN_PRIMARY} onClick={() => setCourseSheet({ course: null })}><Plus size={16} aria-hidden /> Add course</button>
          </div>
        ) : null}
      </div>
      {note ? <Notice>{note}</Notice> : null}
      {can("deals.view") ? <FeeRemindersCard canManage={can("deals.manage")} /> : null}

      {isLoading ? <div className="h-40 animate-pulse rounded-xl bg-surface-low" /> : null}
      {error ? <Notice tone="red">{errorText(error, "Could not load your courses. Try again.")}</Notice> : null}
      {data && data.courses.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#cbd5e1] bg-white px-4 py-10 text-center">
          <p className="text-sm font-bold text-ink">No courses yet</p>
          <p className="mt-1 text-sm text-ink-secondary">Add your first course, then give it a batch with a start date and seats.</p>
        </div>
      ) : null}

      <div className="space-y-3">
        {data?.courses.map((course) => (
          <section key={course.id} className="rounded-xl border border-[#e2e8f0] bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-bold text-ink">{course.name}</h2>
                {course.description ? <p className="mt-0.5 line-clamp-2 text-sm text-ink-secondary">{course.description}</p> : null}
                {money && course.price_paise ? <p className="mt-0.5 text-sm text-ink-secondary">Course fee {rupees(course.price_paise)}</p> : null}
              </div>
              {canManage ? (
                <button type="button" className={BTN_SECONDARY} aria-label={`Edit ${course.name}`} onClick={() => setCourseSheet({ course })}><Pencil size={14} aria-hidden /></button>
              ) : null}
            </div>
            <ul className="mt-3 divide-y divide-[#f1f5f9]">
              {course.batches.length === 0 ? <li className="py-2 text-sm text-ink-secondary">No batches yet.</li> : null}
              {course.batches.map((b) => (
                <li key={b.id}>
                  <button type="button" onClick={() => setOpen({ course, batch: b })} className="flex w-full items-center justify-between gap-3 py-2.5 text-left hover:bg-[#f8fafc]">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-bold text-ink">{b.name}</span>
                      <span className="block text-sm text-ink-secondary">
                        {[b.starts_on ? `Starts ${dayText(b.starts_on)}` : "", b.timing_text ?? "", modeLabel(b.mode)].filter(Boolean).join(" · ")}
                      </span>
                      <span className="block text-sm text-ink-secondary">
                        {seatsText(b)}{b.waitlist_count > 0 ? ` · ${b.waitlist_count} waiting` : ""}{money && b.fee_paise ? ` · ${rupees(b.fee_paise)}` : ""}
                      </span>
                    </span>
                    <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-bold ${STATUS_CLS[b.status]}`}>{b.status === "open" ? "Open" : b.status === "full" ? "Full" : "Closed"}</span>
                  </button>
                </li>
              ))}
            </ul>
            {canManage ? (
              <button type="button" className={`${BTN_SECONDARY} mt-2`} onClick={() => setBatchSheet({ course, batch: null })}><Plus size={14} aria-hidden /> Add batch</button>
            ) : null}
          </section>
        ))}
      </div>

      {courseSheet ? <CourseSheet course={courseSheet.course} canMoney={money || owner} onClose={() => setCourseSheet(null)} onSaved={reload} /> : null}
      {batchSheet ? <BatchSheet course={batchSheet.course} batch={batchSheet.batch} canMoney={money || owner} onClose={() => setBatchSheet(null)} onSaved={reload} /> : null}
      {open ? (
        <BatchPanel course={open.course} batchId={open.batch.id} canManage={canManage} canMoney={can("deals.view")} canDeals={can("deals.manage")}
          onClose={() => { setOpen(null); void mutate(); }}
          onEdit={(b) => { setOpen(null); setBatchSheet({ course: open.course, batch: b }); }} />
      ) : null}
    </div>
  );
}
