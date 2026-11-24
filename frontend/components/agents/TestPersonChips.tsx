"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Plus, RotateCcw, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { companionsApi, type ApiError, type TestPerson } from "@/lib/api";
import { ConfirmModal } from "@/components/ConfirmModal";
import { BTN_PRIMARY, BTN_SECONDARY, INPUT } from "@/components/agents/ui";

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
 * The name box behind "+ New". A plain row, not a <form>: the chips sit inside the message box's form,
 * and a form inside a form makes the browser reload the page on Add ("?n=Prem") instead of saving.
 * Enter adds (but not the Enter that confirms a Tamil / IME word), Escape cancels; neither sends a chat message.
 */
export function NewPersonInput({
  name,
  busy,
  onName,
  onAdd,
  onCancel,
}: {
  name: string;
  busy: boolean;
  onName: (v: string) => void;
  onAdd: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex w-full items-center gap-1.5">
      <label className="sr-only" htmlFor="new-test-customer">Test customer name</label>
      <input
        id="new-test-customer"
        autoFocus
        value={name}
        onChange={(e) => onName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) {
            e.preventDefault(); // else Enter submits the message box around it
            onAdd();
          } else if (e.key === "Escape") {
            onCancel();
          }
        }}
        maxLength={40}
        placeholder="Name (any language)"
        className={cn(INPUT, "h-7 min-w-0 flex-1 px-2.5 py-0 text-[12.5px]")}
      />
      <button type="button" onClick={onAdd} disabled={busy || !name.trim()} className={cn(BTN_PRIMARY, "min-h-7 px-3 text-[12.5px]")}>
        Add
      </button>
    </div>
  );
}

/** "You", or the typed name plus whose profile they ask about: "Vivek · Karthik", "Meena". You is always just "You". */
const personText = (p: TestPerson) => (p.is_you ? "You" : `${p.name}${p.profile_name ? ` · ${p.profile_name}` : ""}`);

/**
 * "chatting as [● Meena ⌄]  ...  Start over" in the picker bar. The pill opens a menu (upward, since the
 * message box sits at the bottom of the screen) listing You and each test customer, a bin to delete one,
 * and "+ New test customer". Picking someone closes the menu and every message is sent as them.
 * Start over wipes the chats and memories of whoever is selected but keeps them in the list. "You" has no bin.
 * A full list (10 test customers) disables "+ New" and says why. Outside click or Escape closes the menu.
 */
export function TestPersonChips({
  people,
  max,
  selectedId,
  characterName,
  onPick,
  onCreated,
  onStartedOver,
  onDeleted,
}: {
  people: TestPerson[] | null;
  max: number;
  /** external_user_id of the person on screen. */
  selectedId: string;
  characterName: string;
  onPick: (id: string) => void;
  onCreated: (p: TestPerson) => void;
  onStartedOver: (p: TestPerson) => void;
  onDeleted: (p: TestPerson) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const list = people ?? [];
  const current = list.find((p) => p.external_user_id === selectedId) ?? list.find((p) => p.is_you);
  const customers = list.filter((p) => !p.is_you).length;
  const full = customers >= max;

  const create = async () => {
    const typed = name.trim();
    if (!typed || busy) return;
    setBusy(true);
    setError("");
    try {
      const person = await companionsApi.createTestPerson(typed);
      setName("");
      setAdding(false);
      setOpen(false);
      onCreated(person);
    } catch (e) {
      setError((e as ApiError).message || "Could not add the test customer.");
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

  const closeMenu = useCallback(() => {
    setOpen(false);
    setAdding(false);
    setName("");
  }, []);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMenu();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, closeMenu]);

  const text = confirm ? confirmText(confirm) : null;
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="shrink-0 text-ink-secondary">chatting as</span>
        <div ref={menuRef} className="relative min-w-0">
          <button
            type="button"
            aria-haspopup="true"
            aria-expanded={open}
            aria-label={current ? `Chatting as ${personText(current)}. Change customer` : "Choose a customer"}
            onClick={() => (open ? closeMenu() : setOpen(true))}
            disabled={people === null}
            className="inline-flex h-7 max-w-[240px] items-center gap-1.5 rounded-full border border-border bg-white px-2.5 text-[12.5px] text-ink transition-colors hover:bg-surface-mid focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:opacity-60"
          >
            <span className="h-2 w-2 shrink-0 rounded-full bg-primary" aria-hidden="true" />
            <span className="truncate">{current ? personText(current) : "Loading…"}</span>
            <ChevronDown size={13} className={cn("shrink-0 text-ink-muted transition-transform", open && "rotate-180")} aria-hidden="true" />
          </button>

          {open && (
            <div role="group" aria-label="Chatting as" className="absolute bottom-full left-0 z-30 mb-1.5 w-[280px] rounded-xl border border-border bg-white p-1 shadow-lg">
              <ul className="max-h-72 overflow-y-auto">
                {list.map((p) => {
                  const on = p.external_user_id === current?.external_user_id;
                  return (
                    <li key={p.external_user_id} className={cn("flex items-center rounded-lg", on ? "bg-surface-mid" : "hover:bg-surface-mid")}>
                      <button
                        type="button"
                        aria-pressed={on}
                        onClick={() => {
                          if (!on) onPick(p.external_user_id);
                          closeMenu();
                        }}
                        title={p.profile_name ? `${p.is_you ? "You" : p.name}, asking about ${p.profile_name}'s profile` : undefined}
                        className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                      >
                        <span className="truncate">{personText(p)}</span>
                        {on && <Check size={14} className="ml-auto shrink-0 text-primary" aria-hidden="true" />}
                      </button>
                      {!p.is_you && (
                        <button
                          type="button"
                          aria-label={`Delete ${p.name}`}
                          onClick={() => {
                            closeMenu();
                            setConfirm({ kind: "delete", person: p });
                          }}
                          className="mr-1 grid h-6 w-6 shrink-0 place-items-center rounded-md text-ink-muted hover:bg-white hover:text-danger focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                        >
                          <Trash2 size={12} aria-hidden="true" />
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
              <div className="mt-1 border-t border-border-subtle px-1.5 pb-1 pt-1.5">
                {adding ? (
                  <NewPersonInput
                    name={name}
                    busy={busy}
                    onName={setName}
                    onAdd={() => void create()}
                    onCancel={() => {
                      setAdding(false);
                      setName("");
                      setError("");
                    }}
                  />
                ) : (
                  <button
                    type="button"
                    disabled={full}
                    title={full ? `You have ${max} test customers, the most allowed. Delete one to add another.` : undefined}
                    onClick={() => {
                      setAdding(true);
                      setError("");
                    }}
                    className="flex w-full items-center gap-1.5 rounded-lg px-1 py-1 text-[13px] font-medium text-primary hover:bg-surface-mid disabled:cursor-not-allowed disabled:text-ink-muted disabled:hover:bg-transparent"
                  >
                    <Plus size={13} aria-hidden="true" /> New test customer
                  </button>
                )}
                <p className="mt-1 px-1 text-[11px] leading-snug text-ink-muted">Each one is a separate visitor to {characterName}, with its own memory.</p>
              </div>
            </div>
          )}
        </div>
        <button
          type="button"
          disabled={!current || busy}
          onClick={() => current && setConfirm({ kind: "start-over", person: current })}
          className={cn(BTN_SECONDARY, "ml-auto min-h-7 shrink-0 gap-1 px-2.5 text-[12.5px]")}
        >
          <RotateCcw size={12} aria-hidden="true" /> Start over
        </button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
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
