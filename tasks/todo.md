# Call Report v1: Tasks

Plan: [tasks/plan.md](plan.md) · Spec: [SPEC.md](../SPEC.md)

## Task 1: Talk metrics (longest monologue, dead air)

**Description:** Add two pure functions to `call_metrics.py` that compute the new talk-balance numbers
from speech segments. Thresholds are constants in `scoring_rules`.

**Acceptance criteria:**
- [ ] `longest_monologue(tele_segs)`: the longest telecaller run, merging gaps < `MONOLOGUE_GAP_S` (1.5 s), rounded to 0.1 s; 0.0 for no segments
- [ ] `dead_air(tele_segs, cust_segs)`: the total of silent gaps ≥ `DEAD_AIR_MIN_S` (3 s), where neither side speaks, counted only after the first speech; 0.0 when empty
- [ ] Overlapping segments from the two sides are handled (union before finding gaps)

**Verification:**
- [ ] Tests pass: `cd backend && python -m pytest tests/test_call_metrics.py -q`

**Dependencies:** None
**Files:** `backend/app/services/call_metrics.py`, `backend/app/services/scoring_rules.py`, `backend/tests/test_call_metrics.py`
**Scope:** S

## Task 2: Report builder (`call_report.py`)

**Description:** New module holding `REPORT_RUBRIC` (prompt text describing the `report` JSON) and
`build_report(raw, lines)`, which turns the AI's raw report into the validated shape from SPEC.md.

**Acceptance criteria:**
- [ ] Every quote goes through `find_quote` with a speaker filter:
  - mood, turning point and objections → customer
  - promises → telecaller
  - coach → either
  - Unmatched items are dropped; time and start come from the matched line
- [ ] Enums are enforced (mood, direction, handling) and caps applied (mood ≤ 8, objections ≤ 6, promises ≤ 6, one coach, one turning point); text is clipped via `clip`
- [ ] Any malformed input (None, wrong types, missing keys) returns `{}` or partial data and never raises

**Verification:**
- [ ] Tests pass: `cd backend && python -m pytest tests/test_call_report.py -q`

**Dependencies:** None
**Files:** `backend/app/services/call_report.py` (new), `backend/tests/test_call_report.py` (new)
**Scope:** S

## Task 3: Wire into Step 2 + pipeline + API fields

**Description:**
- Append `REPORT_RUBRIC` to the Step 2 prompt and add `"report": {...}` to its JSON schema.
- Raise Step 2 max_tokens to 6000.
- Add `MarkResult.report` (first valid vote whose `build_report` is non-empty).
- In `_process`, save `evaluation["report"]` with `talk` + `segments` for stereo calls.
- Add `ai_call_status` to `CALL_CARD_FIELDS`.

**Acceptance criteria:**
- [ ] A real-conversation call saves `evaluation.report`; a stereo call includes `talk` + `segments` (0.1 s rounding); a mono call has neither key
- [ ] A missing or garbage report from the AI leaves `checks`, the score and alerts byte-identical to today (test)
- [ ] `mark_crm_update` keeps `evaluation.report` (test); SIM tenants still get no `evaluation` / `ai_call_status` (existing gate tests pass)

**Verification:**
- [ ] Tests pass: `cd backend && python -m pytest tests/test_call_marking.py tests/test_call_ai_pipeline.py tests/test_call_crm_check.py tests/test_call_review.py -q`
- [ ] Full suite: `cd backend && python -m pytest`

**Dependencies:** Tasks 1, 2
**Files:** `backend/app/services/call_marking.py`, `backend/app/services/call_ai_pipeline.py`, `backend/app/routes/calls.py`, `backend/tests/test_call_marking.py`, `backend/tests/test_call_ai_pipeline.py`
**Scope:** M

## Checkpoint A: Backend + AI quality
- [ ] Full pytest green
- [ ] Read-only eval script (scratchpad, no DB writes) runs `mark_call` on the 3 stored transcripts and reports:
  - quotes found vs dropped (≥ 80%)
  - output size vs the limit
  - failed votes
  - the tips
- [ ] Numbers shown to the user before Phase 2

## Task 4: CallReport panel

**Description:**
- Add TS types for `evaluation.report` and `ai_call_status`, and fix the missing `ai_summary` keys (`objections`, `commitments`, `open_questions`).
- Add pure helpers in `frontend/lib/call-report.ts`.
- Add a `CallReport` component rendered in `CallDetail` for TeleCMI calls, taking an `onSeek(seconds)` prop.

**Acceptance criteria:**
- [ ] Shows the verdict (score pill, temperature chip, next step + date), mood line, turning point, objections, promises (⚠ when risky), coach and talk numbers; each timestamp is a button calling `onSeek(start)`
- [ ] Sections with no data are hidden; a call with no `report` renders exactly as today
- [ ] Uses Anril tokens (teal #038285, navy #0A1528); readable at 375 px

**Verification:**
- [ ] `cd frontend && npm run typecheck && npm run lint && npm test` (helper tests in `lib/call-report.test.ts`)

**Dependencies:** Task 3
**Files:** `frontend/lib/api.ts`, `frontend/lib/call-report.ts` (+ `.test.ts`), `frontend/components/CallReport.tsx` (new), `frontend/app/dashboard/notes/review/CallReview.tsx`
**Scope:** M

## Task 5: SplitAudio

**Description:** Replace the `<audio>` in `CallDetail` with `SplitAudio`. It has:
- a Both / Telecaller only / Lead only toggle (Web Audio `ChannelSplitterNode`; right = telecaller)
- two rows of speech bars from `report.segments`
- a `seek(seconds)` handle used by the CallReport timestamps

**Acceptance criteria:**
- [ ] The toggle isolates one channel; clicking a bar or a timestamp seeks there and plays
- [ ] No segments, or a Web Audio error, gives the plain `<audio controls>` (today's behaviour)
- [ ] The audio graph is created on the first user play (autoplay-safe); switching calls tears it down (no leaked AudioContext)

**Verification:**
- [ ] `cd frontend && npm run typecheck && npm run lint && npm test` (bar-layout helper tests)
- [ ] Manual: listen to ed296fa2 in "Telecaller only" and hear no lead voice

**Dependencies:** Task 4
**Files:** `frontend/components/SplitAudio.tsx` (new), `frontend/lib/call-report.ts`, `frontend/app/dashboard/notes/review/CallReview.tsx`
**Scope:** M

## Checkpoint B: Complete
- [ ] Frontend typecheck, lint and vitest green; backend suite green
- [ ] Ask first: Retry AI on ed296fa2 (live DB) to get a real report
- [ ] UI QA as the UI test tenant (local): screenshots at 375 and 1440 widths, toggle check, a legacy call shows no errors
- [ ] /review on the diff; update `.agents/context/subsystem-notes.md` (Call evaluation: `report` key, segments saved, max_tokens 6000)
- [ ] `git fetch` and check teammate drift; commit to main. No push until told.
