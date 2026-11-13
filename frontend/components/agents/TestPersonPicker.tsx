"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Plus, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionsApi, type ApiError, type TestPerson } from "@/lib/api";
import { ConfirmModal } from "@/components/ConfirmModal";
import { BTN_PRIMARY, INPUT } from "@/components/agents/ui";

/**
 * The owner's test customers, loaded once for the Playground. "You" is first.
 * Example: { people: [You, Asha], max: 10 }. `reload` re-reads the list (a test customer deleted
 * on the Memories page is then gone from the picker too).
 */
export function useTestPeople() {
  const [people, setPeople] = useState<TestPerson[] | null>(null);
  const [max, setMax] = useState(10);
  const [error, setError] = useState("");

  const reload = useCallback(() => {
    companionsApi
      .testPeople()
      .then((r) => {
        setPeople(r.people);
        setMax(r.max);
        setError("");
      })
      .catch((e: Error) => setError(e.message || "Could not load your test customers."));
  }, []);
  useEffect(reload, [reload]);

  return { people, setPeople, max, error, reload };
}

type Confirm = { kind: "start-over" | "delete"; person: TestPerson };

/** The wording of the two confirms. Both name the person and say their chats and memories with every character are deleted. */
function confirmText(c: Confirm): { title: string; description: string; label: string } {
  const { name, is_you } = c.person;
  if (c.kind === "delete") {
    return {
      title: `Delete ${name}?`,
      description: `This deletes ${name}'s chats and memories with every character and removes ${name} from the list. It can't be undone.`,
      label: "Delete",
    };
  }
  return is_you
    ? {
        title: "Start over as You?",
        description: "This deletes your test chats and memories with every character. The next message you send is a first visit.",
        label: "Start over",
      }
    : {
        title: `Start over with ${name}?`,
        description: `This deletes ${name}'s chats and memories with every character. ${name} stays in the list, and the next chat is a first visit.`,
        label: "Start over",
      };
}

/**
 * "Testing as" in the chat box: You, each test customer, "+ New test customer".
 * Example: pick Asha -> the chat is empty and every message is sent as Asha. Start over on Asha
 * wipes her chats and memories but keeps her in the list; Delete also removes her.
 * "You" has Start over only. A full list (10 test customers) disables "+ New" and says why.
 */
export function TestPersonPicker({
  people,
  max,
  selectedId,
  onPick,
  onCreated,
  onStartedOver,
  onDeleted,
  onOpen,
}: {
  people: TestPerson[] | null;
  max: number;
  /** external_user_id of the person on screen. */
  selectedId: string;
  onPick: (id: string) => void;
  onCreated: (p: TestPerson) => void;
  onStartedOver: (p: TestPerson) => void;
  onDeleted: (p: TestPerson) => void;
  /** Called each time the list opens, so it is fresh. */
  onOpen: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [addError, setAddError] = useState("");
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);

  // Click outside or Escape closes the list.
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const list = people ?? [];
  const current = list.find((p) => p.external_user_id === selectedId) ?? list.find((p) => p.is_you);
  const customers = list.filter((p) => !p.is_you).length;
  const full = customers >= max;

  const toggle = () => {
    if (!open) onOpen();
    setOpen(!open);
    setAdding(false);
    setAddError("");
    setError("");
  };

  const create = async () => {
    const typed = name.trim();
    if (!typed || busy) return;
    setBusy(true);
    setAddError("");
    try {
      const person = await companionsApi.createTestPerson(typed);
      setName("");
      setAdding(false);
      setOpen(false);
      onCreated(person);
    } catch (e) {
      setAddError((e as ApiError).message || "Could not add the test customer.");
    } finally {
      setBusy(false);
    }
  };

  const confirmed = async () => {
    if (!confirm || busy) return;
    const { kind, person } = confirm;
    setBusy(true);
    setError("");
    try {
      if (kind === "delete") {
        await companionsApi.deleteTestPerson(person.external_user_id);
        onDeleted(person);
      } else {
        const fresh = await companionsApi.startOverTestPerson(person.external_user_id);
        onStartedOver(fresh);
      }
    } catch (e) {
      setError((e as ApiError).message || "That didn't work. Try again.");
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  };

  const text = confirm ? confirmText(confirm) : null;
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={toggle}
        className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-ink-secondary hover:bg-surface-mid focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <User size={14} aria-hidden="true" />
        Testing as <span className="max-w-[160px] truncate font-semibold text-primary">{current?.name ?? "You"}</span>
        <ChevronDown size={14} aria-hidden="true" className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      )}

      {open && (
        <div role="group" aria-label="Testing as" className="absolute left-0 top-full z-30 mt-1.5 w-[300px] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-white p-1.5 shadow-[0_8px_24px_rgba(10,21,40,0.10)]">
          <ul>
            {list.map((p) => {
              const on = p.external_user_id === current?.external_user_id;
              return (
                <li key={p.external_user_id} className="flex items-center gap-1 rounded-lg hover:bg-surface-mid">
                  <button
                    type="button"
                    aria-current={on ? "true" : undefined}
                    onClick={() => {
                      setOpen(false);
                      if (!on) onPick(p.external_user_id);
                    }}
                    className={cn("flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-ink", on && "font-medium text-primary")}
                  >
                    <span className="truncate">{p.name}</span>
                    {on && <Check size={14} aria-hidden="true" className="shrink-0" />}
                  </button>
                  <button
                    type="button"
                    aria-label={`Start over with ${p.name}`}
                    onClick={() => {
                      setOpen(false);
                      setConfirm({ kind: "start-over", person: p });
                    }}
                    className="shrink-0 rounded-md px-1.5 py-1 text-xs text-ink-secondary hover:text-ink"
                  >
                    Start over
                  </button>
                  {!p.is_you && (
                    <button
                      type="button"
                      aria-label={`Delete ${p.name}`}
                      onClick={() => {
                        setOpen(false);
                        setConfirm({ kind: "delete", person: p });
                      }}
                      className="mr-1 shrink-0 rounded-md px-1.5 py-1 text-xs text-ink-secondary hover:text-danger"
                    >
                      Delete
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="mt-1 border-t border-border-subtle pt-1.5">
            {adding ? (
              <form
                className="space-y-1.5 px-1.5 pb-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  void create();
                }}
              >
                <label className="sr-only" htmlFor="new-test-customer">Test customer name</label>
                <div className="flex gap-1.5">
                  <input
                    id="new-test-customer"
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={40}
                    placeholder="Name (any language)"
                    className={cn(INPUT, "min-w-0 flex-1 py-1.5")}
                  />
                  <button type="submit" disabled={busy || !name.trim()} className={cn(BTN_PRIMARY, "min-h-8 px-3")}>
                    Add
                  </button>
                </div>
                {addError && (
                  <p role="alert" className="text-xs text-danger">
                    {addError}
                  </p>
                )}
              </form>
            ) : (
              <>
                <button
                  type="button"
                  disabled={full || people === null}
                  onClick={() => setAdding(true)}
                  className="flex w-full items-center gap-1.5 rounded-lg px-2.5 py-2 text-left text-sm font-medium text-primary hover:bg-surface-mid disabled:cursor-not-allowed disabled:text-ink-muted disabled:hover:bg-transparent"
                >
                  <Plus size={14} aria-hidden="true" /> New test customer
                </button>
                {full && <p className="px-2.5 pb-1.5 text-xs text-ink-muted">You have {max} test customers, the most allowed. Delete one to add another.</p>}
              </>
            )}
          </div>
        </div>
      )}

      <ConfirmModal
        open={!!confirm}
        onClose={() => !busy && setConfirm(null)}
        onConfirm={() => void confirmed()}
        title={text?.title ?? ""}
        description={text?.description ?? ""}
        confirmLabel={text?.label}
        tone="danger"
        loading={busy}
      />
    </div>
  );
}
