# Reach weekly limit per person — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Reach's fixed "2 campaigns a month" rule with a per-client weekly limit (Sunday–Saturday IST,
default 2, set in Settings), and let the Confirm step list everyone over the limit so the client can pick who
still gets this campaign.

**Architecture:** `services/reach_audience.py` stays the one place that counts and decides; its month window
becomes a week window and it reads the client's number from one `app_settings` row. The preview returns the
over-limit people; the browser sends back the picked phones; `bulk_send` stamps a `send_over_limit` flag onto
each picked person, so Send now, scheduled, drip and deferred runs all carry it (in `leads_json`) and
`send_time_skips` leaves those people out of the skip set. No migration.

**Tech Stack:** FastAPI + supabase-py (backend, `unittest` + `tests/fake_supabase.py`), Next.js + SWR +
Tailwind (frontend, vitest).

**Spec:** `docs/superpowers/specs/2026-11-27-reach-weekly-limit-design.md`

## Global Constraints

- Week = **Sunday 00:00 IST to Saturday 23:59 IST**. IST is UTC+05:30.
- Default **2** when the client never set a number; allowed **1–50** whole numbers; setting key **`reach_weekly_limit`** in `app_settings`.
- Only Reach campaign sends count: `broadcast_recipients` rows with `send_status='sent'`.
- New skip reason **`weekly_limit`**; old rows keep **`monthly_limit`** and its label "skipped: monthly limit".
- Nobody is ticked by default on the Confirm step. A pick is honoured at send time; anyone over the limit and not picked is skipped.
- Settings change applies only on **Save**. Read needs `settings.view`/`settings.manage`; Save needs `settings.manage`.
- Customer-facing copy says "Anril", never "Aira". Plain words: "broadcasts", "this week", "picked".
- No database migration. No change to the opted-out box, the blocked rule, the push-back stop, or the Claude connector's send tools (they send no picks, so over-limit people are skipped as today).
- Backend tests: `cd backend && PYTHONUTF8=1 python -m pytest <file> -q`. Frontend: `cd frontend && npx vitest run <file>`, `npm run typecheck`, `npm run lint`.
- **No commits.** The user commits and pushes their own work; leave every change uncommitted and stage nothing.

## Review Focus

1. **Phone spelled differently in the CSV than in the pick** ("09876 543210" vs "919876543210"): the pick must still apply — stamping compares `phone_key()` on both sides (test in Task 4).
2. **A run deferred to tomorrow** (daily sending cap hit mid-send): the picked flag must survive in the deferred `leads_json` (test in Task 4).
3. **A broken saved value** (`"abc"`, `"0"`, `"99"`, row missing, DB error): sends never crash and use 2 (test in Task 1).
4. **The limit changes between Confirm and send**: picked people still go; people newly over and not picked are skipped (test in Task 1, `send_time_skips`).
5. **A long list** (hundreds over the limit): "Select all" ticks everyone matching the search, not only the rows drawn on screen (test in Task 6).

---

### Task 1: Weekly window, the client's number, and send-anyway (backend core)

Worker: Sonnet.

**Files:**
- Modify: `backend/app/services/reach_audience.py` (module docstring; `MONTHLY_LIMIT`, `month_start_utc`, `monthly_counts`, `send_time_skips`, `_lead_flags`, `classify_people`, `preview_numbers`)
- Test: `backend/tests/test_reach_audience.py` (rewrite `MonthBoundaryTests`, `MonthlyCountTests`, `SendTimeSkipTests`; extend `ClassifyTests`)

**Interfaces:**
- Produces:
  - Constants: `DEFAULT_WEEKLY_LIMIT = 2`, `MIN_WEEKLY_LIMIT = 1`, `MAX_WEEKLY_LIMIT = 50`, `LIMIT_SETTING_KEY = "reach_weekly_limit"`, `SKIP_WEEKLY = "weekly_limit"`, `SKIP_MONTHLY = "monthly_limit"` (kept: only read, for older rows), `SKIP_BLOCKED = "blocked"`, `SKIP_REASONS = frozenset({SKIP_WEEKLY, SKIP_MONTHLY, SKIP_BLOCKED})`. `MONTHLY_LIMIT`, `month_start_utc`, `monthly_counts` are deleted.
  - `week_start_utc(now: datetime | None = None) -> datetime` — Sunday 00:00 IST of the current IST week, as UTC.
  - `week_range_ist(now: datetime | None = None) -> tuple[str, str]` — `("YYYY-MM-DD" Sunday, "YYYY-MM-DD" Saturday)`.
  - `weekly_counts(db, tenant_id: str, keys, *, now=None, exclude_broadcast_id: str | None = None) -> dict[str, int]` — same query as `monthly_counts`, window from `week_start_utc(now)`.
  - `weekly_limit(db, tenant_id: str) -> int` — the saved number; anything missing, non-integer, outside 1–50, or a read error → `DEFAULT_WEEKLY_LIMIT` (log a warning on error).
  - `save_weekly_limit(db, tenant_id: str, value: int) -> int` — upserts `{tenant_id, key: LIMIT_SETTING_KEY, value: str(value), is_secret: False}` on `tenant_id,key`; raises `ValueError` outside 1–50.
  - `send_time_skips(db, tenant_id, phones, *, now=None, exclude_broadcast_id=None, send_anyway=frozenset()) -> tuple[set[str], set[str]]` — `(blocked keys, over-the-weekly-limit keys)`; `over` excludes every key in `send_anyway` (phone keys); fails open as today.
  - `classify_people(...)` — `people` items may carry `"name"`; adds `out["over_limit_people"]: list[{"phone": key, "name": str | None, "this_week": int}]` for the `over_cap` bucket, lead's name first then the person's own name, sorted by `this_week` descending then `phone`.
  - `preview_numbers(...)` — returns `weekly_limit`, `week_start`, `week_end` (from `week_range_ist`) instead of `monthly_limit`; cost still counts only `will_get`.

- [ ] **Step 1: Write the failing tests** in `test_reach_audience.py` (keep `NOW = utc(2026, 11, 20, 10, 0)`, a Friday):

```python
class WeekBoundaryTests(unittest.TestCase):
    def test_week_starts_sunday_midnight_ist(self):
        self.assertEqual(ra.week_start_utc(NOW), utc(2026, 11, 14, 18, 30))
    def test_saturday_late_evening_ist_is_still_this_week(self):   # Sat 28 Nov 23:30 IST
        self.assertEqual(ra.week_start_utc(utc(2026, 11, 28, 18, 0)), utc(2026, 11, 21, 18, 30))
    def test_just_after_sunday_midnight_ist_is_a_new_week(self):    # Sun 29 Nov 00:15 IST
        self.assertEqual(ra.week_start_utc(utc(2026, 11, 28, 18, 45)), utc(2026, 11, 28, 18, 30))
    def test_week_range_is_sunday_to_saturday(self):
        self.assertEqual(ra.week_range_ist(NOW), ("2026-11-15", "2026-11-21"))

class WeeklyLimitSettingTests(unittest.TestCase):
    def test_default_is_two_when_never_set(self):        # no row → 2
    def test_saved_number_is_used(self):                 # value "5" → 5
    def test_broken_values_fall_back_to_two(self):       # "abc", "0", "51", "" → 2 each
    def test_read_error_falls_back_to_two(self):         # db.table raises → 2
    def test_save_rejects_out_of_range(self):            # 0 and 51 → ValueError; 50 saves and reads back 50
```

Port every `MonthlyCountTests` case to `weekly_counts` (IST boundary case: a send at `utc(2026, 11, 14, 18, 0)` — Sat 23:30 IST — does not count; one at `utc(2026, 11, 14, 19, 0)` does). `SendTimeSkipTests`: with limit row `"3"`, a person with 3 campaigns this week is over and one with 2 is not; `send_anyway={that key}` removes them from `over`; with no row, 2 campaigns is over. `ClassifyTests`: `over_limit_people` holds `{"phone": "919876543210", "name": <lead name>, "this_week": 2}` and is sorted most-first.

- [ ] **Step 2: Run and see them fail**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_reach_audience.py -q`
Expected: FAIL — `AttributeError: module 'app.services.reach_audience' has no attribute 'week_start_utc'` (and friends).

- [ ] **Step 3: Implement** the Interfaces above. Week start: `ist = now.astimezone(IST)`, back up `(ist.weekday() + 1) % 7` days, zero the time, convert to UTC. Add `name` to the `_lead_flags` select. Update the module docstring's limit paragraph to the weekly rule.

- [ ] **Step 4: Run and see them pass**

Run: `cd backend && PYTHONUTF8=1 python -m pytest tests/test_reach_audience.py -q`
Expected: PASS.

- [ ] **Step 5: Checkpoint** — no commit (user commits). Leave changes in the working tree.

---

### Task 2: Settings endpoint for the weekly number

Worker: Haiku (exact spec).

**Files:**
- Modify: `backend/app/routes/connections_overview.py`
- Test: `backend/tests/test_reach_limit_setting.py` (new; follow the TestClient + dependency-override pattern in `tests/test_reach_pipeline.py`)

**Interfaces:**
- Consumes: `reach_audience.weekly_limit`, `save_weekly_limit`, `DEFAULT_WEEKLY_LIMIT`, `MIN_WEEKLY_LIMIT`, `MAX_WEEKLY_LIMIT` (Task 1).
- Produces:
  - `GET /api/v1/connections/reach-limit` (dependency `_SETTINGS_VIEW`) → `{"weekly_limit": int, "default": 2, "min": 1, "max": 50}`.
  - `PUT /api/v1/connections/reach-limit` (dependency `require_permission("settings.manage")`) with body `ReachLimitUpdate(weekly_limit: int = Field(ge=1, le=50))` → `{"weekly_limit": int}`.

- [ ] **Step 1: Write the failing tests**: `test_get_returns_two_by_default`, `test_put_saves_and_get_reads_it_back` (PUT 5 → GET 5), `test_put_rejects_0_and_51` (422 each), `test_put_needs_settings_manage` (view-only → 403), `test_one_tenant_never_sees_anothers_number` (T2 saves 9, T1 still reads 2).
- [ ] **Step 2: Run** `cd backend && PYTHONUTF8=1 python -m pytest tests/test_reach_limit_setting.py -q` — Expected: FAIL (404 on the route).
- [ ] **Step 3: Implement** both handlers as plain `def` (threadpool, like the others). Update the module docstring: no longer read-only only.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 3: Preview returns the over-limit people

Worker: Sonnet.

**Files:**
- Modify: `backend/app/routes/upload.py` — `reach_preview()` (~L775-821)
- Test: `backend/tests/test_reach_pipeline.py` (preview tests ~L100-125)

**Interfaces:**
- Consumes: `preview_numbers` output from Task 1.
- Produces: the `/upload/reach-preview` response gains `weekly_limit: int`, `week_start: str`, `week_end: str`, `over_limit_people: [{phone, name, this_week}]`; `monthly_limit` is removed; `over_cap` stays (the count). The `people` list built in `reach_preview` passes `"name"` (group person's `name`, uploaded `lead.name`).

- [ ] **Step 1: Update/write the failing tests**: in `test_group_preview_lists_who_is_left_out_and_the_cost` assert `b["weekly_limit"] == 2` and `b["over_limit_people"] == [{"phone": "919000000005", "name": <name>, "this_week": 2}]`; add `test_preview_uses_the_clients_own_number` (row `"3"` → a person with 2 this week is NOT over, `weekly_limit == 3`); add `test_uploaded_contact_over_the_limit_is_listed_with_the_csv_name` (not a lead yet → name from the CSV row). Assert `"monthly_limit" not in b`.
- [ ] **Step 2: Run** `cd backend && PYTHONUTF8=1 python -m pytest tests/test_reach_pipeline.py -q -k preview` — Expected: FAIL.
- [ ] **Step 3: Implement** — pass `name` into `people`, return the new keys.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 4: Send paths honour picks; weekly skip labels everywhere

Worker: Sonnet.

**Files:**
- Modify: `backend/app/routes/upload.py` — `BulkLeadItem` (~L340), `BulkSendRequest` (~L354), `bulk_send()` (~L1275: stamp after the dedupe at ~L1323; `send_time_skips` call ~L1657), `_execute_immediate_send()` (~L824-962: rename `monthly_limit_keys`→`weekly_limit_keys`, `skipped_monthly`→`skipped_weekly`, `SKIP_MONTHLY`→`SKIP_WEEKLY`; progress/result key `skipped_weekly_limit`; also ~L1232/L1256), the classifier (~L2138-2265, ~L2345) and the history refresh (~L2862)
- Modify: `backend/app/services/broadcast_executor.py` — ~L208-270 (skips), ~L473 (result), `_write_broadcast_history` (~L505, ~L578)
- Modify: `backend/app/routes/tags.py:218` — use `reach_audience.SKIP_REASONS`
- Test: `backend/tests/test_reach_pipeline.py`, `backend/tests/test_reach_scheduled_cap.py`, `backend/tests/test_reach_group_plus_list.py` (rename monthly → weekly where they assert send behaviour)

**Interfaces:**
- Consumes: `send_time_skips(..., send_anyway=...)`, `SKIP_WEEKLY`, `SKIP_MONTHLY`, `SKIP_REASONS`, `phone_key` (Task 1).
- Produces:
  - `BulkLeadItem.send_over_limit: bool = False` — set ONLY by the server; `bulk_send` overwrites it for every person: `lead.send_over_limit = phone_key(lead.phone) in {phone_key(p) for p in body.over_limit_picks}`.
  - `BulkSendRequest.over_limit_picks: list[str] = []` — the phones picked on Confirm (any spelling).
  - Send-time skip key in progress/result/history: `skipped_weekly_limit`. The classifier's `counts` carries both `skipped_weekly_limit` (rows with `weekly_limit`) and `skipped_monthly_limit` (older rows with `monthly_limit`); history records get both; `_write_broadcast_history(..., skipped_weekly_limit: int = 0, skipped_blocked: int = 0)`.
  - Executor: `send_anyway = {phone_key(l.get("phone")) for l in leads_raw if l.get("send_over_limit")}` passed to `send_time_skips`.

- [ ] **Step 1: Write the failing tests**:
  - `test_picked_people_over_the_limit_are_sent_and_the_rest_skipped` (Send now: 3 people over the limit, `over_limit_picks` names 2 → 2 sent, 1 row `opted_out_skip`/`weekly_limit`, `result["skipped_weekly_limit"] == 1`).
  - `test_a_pick_in_another_spelling_still_counts` (CSV `"09000000005"`, pick `"+91 90000 00005"` → sent).
  - `test_a_browser_sent_per_person_flag_is_ignored` (lead item `send_over_limit: true`, top-level list empty → skipped).
  - `test_scheduled_leads_json_carries_the_pick` (schedule → stored `leads_json` person has `send_over_limit: True` only for the picked phone).
  - `test_scheduled_run_sends_picked_over_limit_people` in `test_reach_scheduled_cap.py` (leads_json flag → sent; unflagged over-limit → `weekly_limit` skip).
  - `test_deferred_leads_keep_the_pick` (sender runs out mid Send now → deferred row's `leads_json` keeps `send_over_limit: True`).
  - `test_the_classifier_counts_weekly_and_old_monthly_skips_apart` (one `weekly_limit` row, one `monthly_limit` row → `skipped_weekly_limit == 1`, `skipped_monthly_limit == 1`, neither failed nor opted out).
  - In `tags.py` stats: a `weekly_limit` skip row is not counted as sent (extend the existing tag stats test if present, else add `test_tag_stats_skip_weekly_limit_rows` in `test_reach_pipeline.py`).
- [ ] **Step 2: Run** `cd backend && PYTHONUTF8=1 python -m pytest tests/test_reach_pipeline.py tests/test_reach_scheduled_cap.py tests/test_reach_group_plus_list.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. Update the comments that say "2-offers-a-month" to the weekly rule.
- [ ] **Step 4: Run** the same command, then the whole suite `cd backend && PYTHONUTF8=1 python -m pytest -q` — Expected: PASS, no new failures vs `main`.
- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 5: Settings card "Broadcasts per person per week"

Worker: Haiku (exact spec). UI must match the page's existing cards.

**Files:**
- Modify: `frontend/lib/connectionsApi.ts` — add `ReachLimit = { weekly_limit: number; default: number; min: number; max: number }`, `connectionsApi.reachLimit()` (GET) and `connectionsApi.saveReachLimit(weekly_limit: number)` (PUT, JSON body)
- Create: `frontend/app/dashboard/settings/meta-charges/ReachLimitCard.tsx`
- Modify: `frontend/app/dashboard/settings/meta-charges/page.tsx` — render `<ReachLimitCard />` first in the cards column
- Modify: `frontend/app/dashboard/settings/meta-charges/chargesText.ts` + `chargesText.test.ts` — add `reachLimitProblem(text: string, min: number, max: number): string | null`

**Interfaces:**
- Consumes: Task 2 endpoints.
- Produces: `ReachLimitCard` (no props). `SectionCard` title "Broadcasts per person", description "The most Reach broadcasts one person can get in a week (Sunday to Saturday). Bills, order updates, reminders and replies don't count." Number input (`inputMode="numeric"`, label "Per week"), a Save button disabled until the value changed and is valid, toast "Saved" / the server's error. View-only users (`role !== "owner"` and no `settings.manage`, via `useAuthRole`) see the number and no Save. Helper line under the input: "New clients start at 2. Meta may still block some marketing messages if a person gets too many from all businesses."

- [ ] **Step 1: Write the failing test** in `chargesText.test.ts`: `reachLimitProblem("5",1,50) === null`; `"0"`, `"51"`, `"2.5"`, `""`, `"abc"` each return `"Enter a whole number from 1 to 50."`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run app/dashboard/settings/meta-charges/chargesText.test.ts` — Expected: FAIL.
- [ ] **Step 3: Implement** the helper, the API calls, the card (SWR key `connections:reach-limit`), and the page slot.
- [ ] **Step 4: Run** the vitest command, then `npm run typecheck` and `npm run lint` — Expected: all PASS, no new lint errors.
- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 6: Confirm-step pick-list and weekly labels

Worker: Sonnet. UI must match the opted-out box (orange `rounded-xl border border-orange-200 bg-orange-50/70`, `TickMark`, `AlertTriangle`).

**Files:**
- Create: `frontend/app/dashboard/outbound-leads/overLimit.ts` + `overLimit.test.ts`
- Create: `frontend/app/dashboard/outbound-leads/OverLimitPicker.tsx`
- Modify: `frontend/app/dashboard/outbound-leads/page.tsx` — `ReachPreview` type (~L59), progress/history types (~L54, ~L114, ~L919-930), preview summary block (~L2811-2835), `handleSend` payload (~L1782-1801), send-result text (~L3162-3165), history chips (~L3963)

**Interfaces:**
- Consumes: preview fields from Task 3; `over_limit_picks` request field and `skipped_weekly_limit` from Task 4.
- Produces:
  - `type OverLimitPerson = { phone: string; name: string | null; this_week: number }`
  - `weekRangeLabel(start: string, end: string): string` → `"Sun 15 Nov – Sat 21 Nov"` for `("2026-11-15","2026-11-21")`.
  - `matchPeople(people: OverLimitPerson[], query: string): OverLimitPerson[]` — case-insensitive on name, digits-only match on phone.
  - `toggleAll(picked: Set<string>, shown: OverLimitPerson[], on: boolean): Set<string>` — adds/removes every phone in `shown` (the full search result, not only drawn rows).
  - `keepKnown(picked: Set<string>, people: OverLimitPerson[]): Set<string>` — drops picks no longer in the list (after a re-preview).
  - `OverLimitPicker({ people, limit, weekStart, weekEnd, picked, onChange })` — collapsed by default; header "N people already got L broadcasts this week (Sun … – Sat …). They'll be skipped unless you pick them." + button "Show N people ▾"/"Hide"; open: "Select all · X of N picked" checkbox (reflects all/some/none of the search result), search input (h-10), rows (tick · name or "—" · formatted phone · "K this week"), at most 200 rows drawn with "Showing 200 of M — search to find others".
  - page.tsx: `overLimitPicked` state (`Set<string>`), reset to empty when the audience/step resets, `keepKnown` after each preview; summary part `"N over this week's limit (X picked)"`; "will get it" = `will_get + X`; cost = `(will_get + X) × rate_inr`; footnote "Each person gets at most L broadcasts a week (Sunday to Saturday). You can change this in Settings › Limits & Meta charges. It's checked again when the message goes out." Payload adds `over_limit_picks: [...overLimitPicked]`. Group send-count check (`reachPreview?.will_get`) uses `will_get + X`. Send result: "N skipped: weekly limit (they already had this week's broadcasts)". History: chip "N skipped: weekly limit" from `skipped_weekly_limit`; keep the existing "skipped: monthly limit" chip for older records.

- [ ] **Step 1: Write the failing tests** in `overLimit.test.ts`: `weekRangeLabel` value above; `matchPeople` finds "ravi" in "Ravi Kumar" and "98765" in "919876543210", ignores spaces in the query; `toggleAll` on a 300-person search result picks all 300 and off removes only those 300 (a pick outside the search stays); `keepKnown` drops a phone no longer listed.
- [ ] **Step 2: Run** `cd frontend && npx vitest run app/dashboard/outbound-leads/overLimit.test.ts` — Expected: FAIL.
- [ ] **Step 3: Implement** `overLimit.ts`, `OverLimitPicker.tsx`, and the page wiring. Place the picker right under the "will get it" summary card (it works for groups and lists; the risk-audit card only runs for lists).
- [ ] **Step 4: Run** the vitest command, `npm run typecheck`, `npm run lint` — Expected: all PASS.
- [ ] **Step 5: Checkpoint** — no commit.

---

### Task 7: Notes, review, and a live check

Worker: planner (Opus) — review and QA are never delegated.

**Files:**
- Modify: `.agents/context/subsystem-notes.md` — "Broadcast delivery & retry": one bullet on the weekly limit (`reach_weekly_limit`, Sunday IST week, `send_over_limit` stamped by `bulk_send` and carried in `leads_json`, `weekly_limit` vs old `monthly_limit` rows).

- [ ] **Step 1:** `/code-review` on every worker diff, then `/simplify`.
- [ ] **Step 2:** Full checks: `cd backend && PYTHONUTF8=1 python -m pytest -q`; `cd frontend && npx vitest run && npm run typecheck && npm run lint`. Expected: all PASS.
- [ ] **Step 3:** UI QA as the UI test tenant (backend via `bash scripts/dev-backend.sh` — safe mode, no real sends — frontend on `NEXT_PUBLIC_API_URL=http://localhost:8000`): Settings card saves 5 and reloads 5; on Confirm, a CSV with people over the limit shows the box, ticking 3 of 5 moves "will get it" and the cost by 3; screenshots of both.
- [ ] **Step 4:** `git fetch` and check `HEAD..origin/main` for teammate commits on these files; rebase and re-run tests if any.
- [ ] **Step 5:** Report to the user with the diff summary and screenshots. No commit, no push.
