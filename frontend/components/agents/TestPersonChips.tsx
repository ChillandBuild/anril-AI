"use client";
import { useCallback, useEffect, useState } from "react";
import { Plus, RotateCcw, X } from "lucide-react";
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
    <div className="flex items-center gap-1.5">
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
        className={cn(INPUT, "h-7 w-[160px] min-w-0 px-2.5 py-0 text-[12.5px]")}
      />
      <button type="button" onClick={onAdd} disabled={busy || !name.trim()} className={cn(BTN_PRIMARY, "min-h-7 px-3 text-[12.5px]")}>
        Add
      </button>
    </div>
  );
}

const CHIP = "inline-flex min-h-7 items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12.5px] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30";
const CHIP_OFF = "border-border bg-white text-ink-secondary hover:bg-surface-mid";
const CHIP_ON = "border-primary bg-primary text-white";

/**
 * "Chatting as a customer" in the picker bar: a chip for You and each test customer, "+ New", and "Start over".
 * Example: [You] [Meena x] [+ New] ... Start over. One tap on Meena -> the chat is hers and every message is sent as Meena.
 * The x on her chip deletes her (after a confirm); Start over wipes the chats and memories of whoever is selected
 * but keeps them in the list. "You" has no x. A full list (10 test customers) disables "+ New" and says why.
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

  const text = confirm ? confirmText(confirm) : null;
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="text-ink-secondary">Chatting as a customer:</span>
        <div role="group" aria-label="Chatting as" className="flex flex-wrap items-center gap-1.5">
          {list.map((p) => {
            const on = p.external_user_id === current?.external_user_id;
            return (
              <span key={p.external_user_id} className={cn(CHIP, "gap-0.5 p-0", on ? CHIP_ON : CHIP_OFF)}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => !on && onPick(p.external_user_id)}
                  className={cn("max-w-[140px] truncate rounded-full py-0.5 pl-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30", p.is_you && "pr-2.5", !p.is_you && "pr-0.5")}
                >
                  {p.is_you ? "You" : p.name}
                </button>
                {!p.is_you && (
                  <button
                    type="button"
                    aria-label={`Delete ${p.name}`}
                    onClick={() => setConfirm({ kind: "delete", person: p })}
                    className={cn("mr-1 grid h-5 w-5 place-items-center rounded-full", on ? "hover:bg-white/20" : "hover:bg-surface-mid hover:text-danger")}
                  >
                    <X size={12} aria-hidden="true" />
                  </button>
                )}
              </span>
            );
          })}
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
              disabled={full || people === null}
              title={full ? `You have ${max} test customers, the most allowed. Delete one to add another.` : undefined}
              onClick={() => {
                setAdding(true);
                setError("");
              }}
              className={cn(CHIP, CHIP_OFF, "border-dashed font-medium text-primary disabled:cursor-not-allowed disabled:text-ink-muted disabled:hover:bg-white")}
            >
              <Plus size={12} aria-hidden="true" /> New
            </button>
          )}
        </div>
        <button
          type="button"
          disabled={!current || busy}
          onClick={() => current && setConfirm({ kind: "start-over", person: current })}
          className={cn(BTN_SECONDARY, "ml-auto min-h-7 gap-1 px-2.5 text-[12.5px]")}
        >
          <RotateCcw size={12} aria-hidden="true" /> Start over
        </button>
      </div>
      <p className="text-xs text-ink-muted">{characterName} treats each one as a separate visitor with its own memory.</p>
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
