import { apiFetch } from "@/lib/api";

// Education › Courses & batches + fee instalments. Backend: app/routes/courses.py. Money (paise) is left out of
// the answers for people without orders access, so every money field is optional.

export type BatchMode = "online" | "offline" | "both";
export type BatchStatus = "open" | "full" | "closed";
export type PayMethod = "cash" | "upi" | "card" | "bank_transfer" | "other";

export interface Batch {
  id: string;
  course_item_id: string;
  name: string;
  starts_on: string | null;
  timing_text: string | null;
  mode: BatchMode;
  seats_total: number;
  seats_filled: number;
  /** Enrolled but nothing paid yet. */
  seats_waiting: number;
  seats_left: number;
  waitlist_count: number;
  teacher_name: string | null;
  status: BatchStatus;
  /** What staff saved: "full" here means they switched it to full by hand. */
  stored_status: BatchStatus;
  fee_paise?: number;
}

export interface Course {
  id: string;
  name: string;
  description: string | null;
  price_paise?: number;
  batches: Batch[];
}

export interface CourseList {
  courses: Course[];
  can_see_money: boolean;
}

export interface FeePart {
  index: number;
  due_on: string;
  amount_paise: number;
  paid: boolean;
  late: boolean;
  payment_id: string | null;
  paid_at: string | null;
  receipt_no: string | null;
  method: string | null;
  by_name: string | null;
  /** Paid by money put on the order itself (Orders page or a pay link): no receipt of ours. */
  on_order?: boolean;
}

export interface FeePlan {
  id: string;
  deal_id: string;
  parts: FeePart[];
  paid_paise: number;
  total_paise: number;
}

export interface Student {
  id: string;
  lead_id: string;
  name: string | null;
  phone: string;
  parent_phone: string | null;
  deal_id: string | null;
  deal_number: number | null;
  paid: boolean;
  created_at: string | null;
  /** Money fields only come with orders access. */
  fee_plan?: FeePlan | null;
  total_paise?: number;
  paid_paise?: number;
}

export interface WaitlistEntry {
  id: string;
  name: string | null;
  phone: string;
  created_at: string | null;
  source?: "staff" | "ai";
  told_at?: string | null; // v9.2 #216: when we told them a seat is free
  told_via?: "text" | "template" | "staff" | null;
}

export interface BatchDetail {
  batch: Batch;
  students: Student[];
  waitlist: WaitlistEntry[];
  next_open_batch: Batch | null;
  seat_template?: string | null; // batch_seat_free: APPROVED | PENDING | REJECTED | null (never sent)
}

export interface Receipt {
  id: string;
  receipt_no: string;
  paid_at: string | null;
  method: string;
  amount_paise: number;
  part_number: number;
  parts_total: number;
  business_name: string;
  student_name: string;
  phone: string;
  course_name: string;
  batch_name: string;
  fee_total_paise: number;
  balance_paise: number;
  paid_by: string | null;
}

export interface ReminderState {
  enabled: boolean;
  /** APPROVED | PENDING | REJECTED, or null when it was never sent to WhatsApp. */
  template: string | null;
  template_body: string;
  /** v9.2 #217: the same reminder with a Razorpay pay link for the part; status as above. */
  link_template?: string | null;
  link_template_body?: string;
}

export interface BatchBody {
  name?: string;
  starts_on?: string | null;
  timing_text?: string | null;
  mode?: BatchMode;
  seats_total?: number;
  fee_paise?: number;
  teacher_name?: string | null;
  status?: BatchStatus;
}

export interface PartBody {
  due_on: string;
  amount_paise: number;
}

export interface EnrolBody {
  name?: string;
  phone: string;
  parent_phone?: string;
  parts?: PartBody[];
  instalments?: number;
  first_due_on?: string;
}

const BASE = "/api/v1/courses";
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});
const id = encodeURIComponent;

/** Courses & batches tiles (GET /courses/summary). Money only for people who may see it. */
export interface CoursesSummary {
  students: number;
  batches: number;
  seats_left_this_month: number;
  waitlist: number;
  full_batches: string[];
  demo_week: number;
  demo_joined: number;
  fees_due_students: number;
  fees_due_paise?: number;
}

/** One student on Fee instalments. */
export interface FeeInstalment {
  plan_id: string;
  deal_id: string;
  enrolment_id: string;
  lead_id: string | null;
  student_name: string | null;
  phone: string | null;
  course_name: string | null;
  batch_name: string | null;
  parts: number;
  total_paise: number;
  paid_paise: number;
  next_index: number | null;
  next_due: string | null;
  next_paise: number;
  status: "paid" | "late" | "due_soon" | "on_track";
  days_late: number;
}

export const coursesApi = {
  list: () => apiFetch<CourseList>(BASE),
  summary: () => apiFetch<CoursesSummary>(`${BASE}/summary`),
  feeInstalments: () => apiFetch<{ rows: FeeInstalment[] }>(`${BASE}/fee-instalments`),
  partPayLink: (planId: string, partIndex: number) =>
    apiFetch<{ url: string }>(`${BASE}/fee-plans/${id(planId)}/parts/${partIndex}/pay-link`, json("POST")),
  createCourse: (body: { name: string; description?: string; price_paise?: number }) =>
    apiFetch<{ id: string; name: string }>(BASE, json("POST", body)),
  updateCourse: (courseId: string, body: { name?: string; description?: string | null; price_paise?: number }) =>
    apiFetch<{ id: string; name: string }>(`${BASE}/${id(courseId)}`, json("PATCH", body)),
  createBatch: (courseId: string, body: BatchBody) =>
    apiFetch<{ id: string }>(`${BASE}/${id(courseId)}/batches`, json("POST", body)),
  updateBatch: (batchId: string, body: BatchBody) =>
    apiFetch<{ id: string }>(`${BASE}/batches/${id(batchId)}`, json("PATCH", body)),
  batch: (batchId: string) => apiFetch<BatchDetail>(`${BASE}/batches/${id(batchId)}`),
  enrol: (batchId: string, body: EnrolBody) =>
    apiFetch<{ enrolment_id: string; deal_id: string; deal_number: number | null; fee_plan_id: string }>(
      `${BASE}/batches/${id(batchId)}/enrol`, json("POST", body)),
  drop: (enrolmentId: string) =>
    apiFetch<{ dropped: boolean; order_cancelled: boolean; paid_paise: number }>(`${BASE}/enrolments/${id(enrolmentId)}/drop`, json("POST")),
  joinWaitlist: (batchId: string, body: { phone: string; name?: string }) =>
    apiFetch<{ id: string }>(`${BASE}/batches/${id(batchId)}/waitlist`, json("POST", body)),
  submitSeatTemplate: () => apiFetch<{ seat_template: string | null }>(`${BASE}/seat-template`, json("POST")),
  leaveWaitlist: (waitlistId: string) => apiFetch<{ ok: boolean }>(`${BASE}/waitlist/${id(waitlistId)}`, json("DELETE")),
  saveFeePlan: (enrolmentId: string, parts: PartBody[]) =>
    apiFetch<FeePlan>(`${BASE}/enrolments/${id(enrolmentId)}/fee-plan`, json("PUT", { parts })),
  payPart: (planId: string, index: number, method: PayMethod) =>
    apiFetch<Receipt>(`${BASE}/fee-plans/${id(planId)}/parts/${index}/pay`, json("POST", { method })),
  receipt: (paymentId: string) => apiFetch<Receipt>(`${BASE}/receipts/${id(paymentId)}`),
  reminders: () => apiFetch<ReminderState>(`${BASE}/fee-reminders`),
  setReminders: (enabled: boolean) => apiFetch<ReminderState>(`${BASE}/fee-reminders`, json("PUT", { enabled })),
  submitReminderTemplate: () => apiFetch<ReminderState>(`${BASE}/fee-reminders/template`, json("POST")),
  setupDemoClass: () =>
    apiFetch<{ service_id: string; created: boolean; has_staff?: boolean }>(`${BASE}/demo-class`, json("POST")),
};
