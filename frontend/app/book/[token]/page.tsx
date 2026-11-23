"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import {
  PublicBookingError,
  createBooking,
  fetchBookingInfo,
  fetchFreeDays,
  fetchFreeTimes,
  type PublicBookingInfo,
  type PublicService,
  type PublicSlot,
} from "@/lib/publicBookingApi";
import {
  STEPS,
  STEP_TITLES,
  buildDayGrid,
  checkIndianMobile,
  checkName,
  classifyError,
  cleanPhoneInput,
  errorMessage,
  errorText,
  NAME_MAX,
  flowReducer,
  formatDay,
  formatDuration,
  formatTime,
  formatWhen,
  groupTimes,
  initialFlow,
  rupees,
  staffChoices,
  stepIndex,
  type Step,
} from "@/lib/publicBookingLogic";
import { BookLoading, BookMessage, BookShell, ErrorNote, StepHeading, choiceBtn, primaryBtn, secondaryBtn } from "./BookShell";

// The customer's booking page, opened from the business's booking link. No sign-in: the link's
// secret token is the key. One question at a time: service, staff, day, time, name + phone.

export default function BookPage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [info, setInfo] = useState<PublicBookingInfo | null | undefined>(undefined);
  const [loadFailed, setLoadFailed] = useState(false);
  const [flow, dispatch] = useReducer(flowReducer, initialFlow);

  const [freeDays, setFreeDays] = useState<string[] | null>(null);
  const [times, setTimes] = useState<PublicSlot[] | null>(null);
  const [stepLoading, setStepLoading] = useState(false);
  const [stepError, setStepError] = useState("");
  const [notice, setNotice] = useState("");

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; phone?: string }>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const headingRef = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  const reqId = useRef(0);

  const loadInfo = useCallback(() => {
    setLoadFailed(false);
    setInfo(undefined);
    fetchBookingInfo(token)
      .then(setInfo)
      .catch((e) => {
        if (e instanceof PublicBookingError && e.status === 404) setInfo(null);
        else setLoadFailed(true);
      });
  }, [token]);

  useEffect(loadInfo, [loadInfo]);

  useEffect(() => {
    if (info) document.title = `Book a time · ${info.business_name}`;
  }, [info]);

  // Move keyboard focus to each new step's heading (not on first load).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [flow.step]);

  const service: PublicService | undefined = useMemo(
    () => info?.services.find((s) => s.id === flow.serviceId),
    [info, flow.serviceId],
  );
  const staff = useMemo(
    () => (info && flow.serviceId ? staffChoices(info.resources, flow.serviceId) : []),
    [info, flow.serviceId],
  );
  const staffName = staff.find((s) => s.id === flow.resourceId)?.name;
  const [now, setNow] = useState(() => Date.now());

  async function loadDays(serviceId: string, resourceId: string) {
    const my = ++reqId.current;
    setNow(Date.now());
    setStepLoading(true);
    setStepError("");
    setFreeDays(null);
    try {
      const dates = await fetchFreeDays(token, serviceId, resourceId);
      if (my === reqId.current) setFreeDays(dates);
    } catch (e) {
      if (my === reqId.current) {
        setStepError(e instanceof PublicBookingError ? errorText(e.status, e.detail) : errorMessage("other"));
      }
    } finally {
      if (my === reqId.current) setStepLoading(false);
    }
  }

  async function loadTimes(serviceId: string, resourceId: string, date: string) {
    const my = ++reqId.current;
    setStepLoading(true);
    setStepError("");
    setTimes(null);
    try {
      const slots = await fetchFreeTimes(token, serviceId, resourceId, date);
      if (my === reqId.current) setTimes(slots);
    } catch (e) {
      if (my === reqId.current) {
        setStepError(e instanceof PublicBookingError ? errorText(e.status, e.detail) : errorMessage("other"));
      }
    } finally {
      if (my === reqId.current) setStepLoading(false);
    }
  }

  function pickService(id: string) {
    setNotice("");
    setStepError("");
    dispatch({ type: "service", id });
  }

  function pickStaff(id: string) {
    if (!flow.serviceId) return;
    setNotice("");
    dispatch({ type: "staff", id });
    void loadDays(flow.serviceId, id);
  }

  function pickDay(date: string) {
    if (!flow.serviceId || !flow.resourceId) return;
    setNotice("");
    dispatch({ type: "day", date });
    void loadTimes(flow.serviceId, flow.resourceId, date);
  }

  function pickTime(slot: PublicSlot) {
    setSubmitError("");
    dispatch({ type: "time", slot });
  }

  function edit(step: Step) {
    setNotice("");
    setSubmitError("");
    dispatch({ type: "edit", step });
    if (flow.serviceId && flow.resourceId) {
      if (step === "day") void loadDays(flow.serviceId, flow.resourceId);
      if (step === "time" && flow.date) void loadTimes(flow.serviceId, flow.resourceId, flow.date);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting || !flow.serviceId || !flow.resourceId || !flow.slot) return;
    const n = checkName(name);
    const p = checkIndianMobile(phone);
    const errs = { name: n.ok ? undefined : n.message, phone: p.ok ? undefined : p.message };
    setFieldErrors(errs);
    if (!n.ok || !p.ok) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const created = await createBooking(token, {
        service_id: flow.serviceId,
        resource_id: flow.resourceId === "any" ? "any" : flow.slot.resource_id,
        start_at: flow.slot.start_at,
        phone: p.phone,
        name: n.name,
      });
      try {
        sessionStorage.setItem(
          `anril-booking:${created.id}`,
          JSON.stringify({ hold_until: created.hold_until, service_id: flow.serviceId, resource_id: flow.slot.resource_id }),
        );
      } catch {
        /* private mode: the status page works without it */
      }
      router.push(`/book/${encodeURIComponent(token)}/b/${encodeURIComponent(created.id)}`);
    } catch (err) {
      const kind = err instanceof PublicBookingError ? classifyError(err.status, err.detail) : "other";
      if (kind === "slot_taken") {
        setNotice(errorMessage("slot_taken"));
        setSubmitError("");
        dispatch({ type: "slotTaken" });
        void loadTimes(flow.serviceId, flow.resourceId, flow.date!);
      } else {
        setSubmitError(errorMessage(kind, err instanceof PublicBookingError ? err.detail : ""));
      }
      setSubmitting(false);
    }
  }

  if (loadFailed) {
    return (
      <BookShell>
        <BookMessage action={<button type="button" onClick={loadInfo} className={secondaryBtn}>Try again</button>}>
          This page couldn&apos;t be loaded. Check your internet and try again.
        </BookMessage>
      </BookShell>
    );
  }
  if (info === undefined) return <BookShell><BookLoading /></BookShell>;
  if (info === null) {
    return (
      <BookShell>
        <BookMessage>This booking link is not working. Ask the business for a new one.</BookMessage>
      </BookShell>
    );
  }
  if (info.services.length === 0) {
    return (
      <BookShell>
        <Header name={info.business_name} />
        <BookMessage>Online booking isn&apos;t ready yet. Please message or call the business.</BookMessage>
      </BookShell>
    );
  }

  const current = flow.step;
  const stepNo = stepIndex(current) + 1;
  const grid = buildDayGrid(now, info.rules.days_ahead, freeDays ?? []);
  const anyFreeDay = grid.some((c) => c.enabled);
  const groups = groupTimes(times ?? [], flow.resourceId === "any");

  return (
    <BookShell>
      <Header name={info.business_name} />
      <p className="mb-3 text-xs font-semibold text-slate-500" aria-live="polite">
        Step {stepNo} of {STEPS.length}
      </p>

      {notice && <ErrorNote>{notice}</ErrorNote>}

      <ol className="mt-3 space-y-3">
        {/* 1. Service */}
        <Card>
          {current === "service" ? (
            <>
              <StepHeading ref={headingRef}>{STEP_TITLES.service}</StepHeading>
              <ul className="mt-3 space-y-2">
                {info.services.map((s) => (
                  <li key={s.id}>
                    <button type="button" onClick={() => pickService(s.id)} className={choiceBtn}>
                      <span className="min-w-0">
                        <span className="block text-sm font-bold text-slate-900">{s.name}</span>
                        <span className="block text-xs text-slate-500">
                          {formatDuration(s.duration_min)}
                          {s.price_paise ? ` · ${rupees(s.price_paise)}` : ""}
                        </span>
                      </span>
                      {s.advance_paise ? (
                        <span className="shrink-0 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                          {rupees(s.advance_paise)} advance
                        </span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <Summary label="Booking" value={service?.name ?? ""} detail={service ? formatDuration(service.duration_min) : ""} onChange={() => edit("service")} />
          )}
        </Card>

        {/* 2. Staff */}
        {stepIndex(current) >= 1 && (
          <Card>
            {current === "staff" ? (
              <>
                <StepHeading ref={headingRef}>{STEP_TITLES.staff}</StepHeading>
                {staff.length === 0 ? (
                  <p className="mt-3 text-sm text-slate-600">No one is free for this right now. Please pick something else or call the business.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {staff.map((s) => (
                      <li key={s.id}>
                        <button type="button" onClick={() => pickStaff(s.id)} className={choiceBtn}>
                          <span className="text-sm font-bold text-slate-900">{s.name}</span>
                          {s.id === "any" && <span className="text-xs text-slate-500">Earliest time</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <Summary label="With" value={staffName ?? ""} onChange={() => edit("staff")} />
            )}
          </Card>
        )}

        {/* 3. Day */}
        {stepIndex(current) >= 2 && (
          <Card>
            {current === "day" ? (
              <>
                <StepHeading ref={headingRef}>{STEP_TITLES.day}</StepHeading>
                {stepLoading ? (
                  <Spinner />
                ) : stepError ? (
                  <ErrorNote>{stepError}</ErrorNote>
                ) : freeDays && !anyFreeDay ? (
                  <p className="mt-3 text-sm text-slate-600">
                    No free days in the next {info.rules.days_ahead} days. Try someone else, or call the business.
                  </p>
                ) : (
                  <ul className="mt-3 grid grid-cols-3 gap-2 min-[400px]:grid-cols-4">
                    {grid.map((c) => (
                      <li key={c.date}>
                        <button
                          type="button"
                          disabled={!c.enabled}
                          onClick={() => pickDay(c.date)}
                          aria-label={`${c.weekday} ${c.day} ${c.month}${c.isToday ? ", today" : ""}${c.enabled ? "" : ", full"}`}
                          className="flex min-h-[64px] w-full flex-col items-center justify-center rounded-xl border border-slate-200 bg-white px-1 py-2 hover:border-emerald-400 hover:bg-emerald-50/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 disabled:cursor-not-allowed disabled:border-slate-100 disabled:bg-slate-50 disabled:text-slate-300 disabled:hover:bg-slate-50"
                        >
                          <span className="text-xs font-semibold">{c.isToday ? "Today" : c.weekday}</span>
                          <span className="text-lg font-bold leading-6">{c.day}</span>
                          <span className="text-xs">{c.month}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <Summary label="Day" value={flow.date ? formatDay(`${flow.date}T06:30:00Z`) : ""} onChange={() => edit("day")} />
            )}
          </Card>
        )}

        {/* 4. Time */}
        {stepIndex(current) >= 3 && (
          <Card>
            {current === "time" ? (
              <>
                <StepHeading ref={headingRef}>{STEP_TITLES.time}</StepHeading>
                {stepLoading ? (
                  <Spinner />
                ) : stepError ? (
                  <ErrorNote>{stepError}</ErrorNote>
                ) : times && groups.length === 0 ? (
                  <p className="mt-3 text-sm text-slate-600">No free times left that day. Please pick another day.</p>
                ) : (
                  <div className="mt-3 space-y-4">
                    {groups.map((g) => (
                      <section key={g.part} aria-label={g.part}>
                        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">{g.part}</h3>
                        <ul className="grid grid-cols-3 gap-2">
                          {g.slots.map((s) => (
                            <li key={`${s.start_at}-${s.resource_id}`}>
                              <button
                                type="button"
                                onClick={() => pickTime(s)}
                                className="min-h-[48px] w-full rounded-xl border border-slate-200 bg-white px-1 py-2 text-sm font-bold text-slate-900 hover:border-emerald-400 hover:bg-emerald-50/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
                              >
                                {formatTime(s.start_at)}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))}
                  </div>
                )}
                {!stepLoading && (
                  <button type="button" onClick={() => edit("day")} className="mt-4 text-sm font-semibold text-emerald-700 underline underline-offset-2">
                    Pick another day
                  </button>
                )}
              </>
            ) : (
              <Summary
                label="Time"
                value={flow.slot ? formatTime(flow.slot.start_at) : ""}
                detail={flow.resourceId === "any" && flow.slot ? `with ${flow.slot.resource_name}` : undefined}
                onChange={() => edit("time")}
              />
            )}
          </Card>
        )}

        {/* 5. Details */}
        {current === "details" && flow.slot && service && (
          <Card>
            <StepHeading ref={headingRef}>{STEP_TITLES.details}</StepHeading>
            <p className="mt-1 text-sm text-slate-600">
              {service.name}, {formatWhen(flow.slot.start_at)} with {flow.slot.resource_name}
            </p>
            <form onSubmit={submit} noValidate className="mt-4 space-y-4">
              <div>
                <label htmlFor="bk-name" className="mb-1 block text-sm font-semibold text-slate-800">Your name</label>
                <input
                  id="bk-name"
                  type="text"
                  autoComplete="name"
                  value={name}
                  maxLength={NAME_MAX}
                  onChange={(e) => setName(e.target.value)}
                  aria-invalid={!!fieldErrors.name}
                  aria-describedby={fieldErrors.name ? "bk-name-err" : undefined}
                  className="min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-3 text-base text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200"
                />
                {fieldErrors.name && <p id="bk-name-err" role="alert" className="mt-1 text-sm text-rose-700">{fieldErrors.name}</p>}
              </div>
              <div>
                <label htmlFor="bk-phone" className="mb-1 block text-sm font-semibold text-slate-800">Mobile number</label>
                <div className="flex min-h-[48px] items-stretch overflow-hidden rounded-xl border border-slate-300 bg-white focus-within:border-emerald-500 focus-within:ring-2 focus-within:ring-emerald-200">
                  <span className="flex items-center border-r border-slate-200 bg-slate-50 px-3 text-base font-semibold text-slate-600" aria-hidden="true">+91</span>
                  <input
                    id="bk-phone"
                    type="tel"
                    inputMode="numeric"
                    autoComplete="tel-national"
                    value={phone}
                    onChange={(e) => setPhone(cleanPhoneInput(e.target.value))}
                    aria-invalid={!!fieldErrors.phone}
                    aria-describedby={fieldErrors.phone ? "bk-phone-err" : "bk-phone-hint"}
                    placeholder="98765 43210"
                    className="min-w-0 flex-1 px-3 text-base text-slate-900 focus:outline-none"
                  />
                </div>
                {fieldErrors.phone ? (
                  <p id="bk-phone-err" role="alert" className="mt-1 text-sm text-rose-700">{fieldErrors.phone}</p>
                ) : (
                  <p id="bk-phone-hint" className="mt-1 text-xs text-slate-500">You confirm this number on WhatsApp after you book.</p>
                )}
              </div>
              {service.advance_paise ? (
                <p className="rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
                  This booking needs a {rupees(service.advance_paise)} advance. You&apos;ll pay it after you confirm your number on WhatsApp.
                </p>
              ) : null}
              {submitError && <ErrorNote>{submitError}</ErrorNote>}
              <button type="submit" disabled={submitting} className={primaryBtn}>
                {submitting && <Loader2 size={18} className="animate-spin" />} {submitting ? "Booking…" : "Book"}
              </button>
            </form>
          </Card>
        )}
      </ol>
    </BookShell>
  );
}

function Header({ name }: { name: string }) {
  return (
    <header className="mb-4">
      <h1 className="text-xl font-bold text-slate-900">{name}</h1>
      <p className="text-sm text-slate-500">Book a time</p>
    </header>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <li className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">{children}</li>;
}

function Spinner() {
  return (
    <div role="status" aria-label="Loading" className="flex justify-center py-8">
      <Loader2 className="animate-spin text-slate-400" />
    </div>
  );
}

function Summary({ label, value, detail, onChange }: { label: string; value: string; detail?: string; onChange: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
        <p className="truncate text-sm font-bold text-slate-900">
          {value}
          {detail ? <span className="font-normal text-slate-500"> · {detail}</span> : null}
        </p>
      </div>
      <button
        type="button"
        onClick={onChange}
        aria-label={`Change ${label.toLowerCase()}`}
        className="shrink-0 rounded-lg px-3 py-2 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700"
      >
        Change
      </button>
    </div>
  );
}
