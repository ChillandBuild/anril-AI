# Implementation Plan: Call Report v1 (manager-only)

Spec: [SPEC.md](../SPEC.md) (approved 2026-10-18). Task checklist: [tasks/todo.md](todo.md).

## Overview

A per-call report on Notes → Review (CallDetail in CallReview.tsx) covering:
- verdict
- mood line and turning point
- objections (handled or dodged)
- promises, with risky ones flagged
- one coaching tip
- talk balance
- split audio with click-to-seek

The AI fields ride on the existing Step 2 request (`mark_call`). The talk numbers and speech bars come
from the speech segments the pipeline already computes and today discards. Everything is stored under
`call_logs.evaluation.report`, with no migration.

## Resolved open questions

| Question | Answer | Evidence |
|---|---|---|
| Full transcript for managers? | No. Clickable quotes only (privacy rule kept) | User approval, 2026-10-18 |
| Lead temperature source | `call_logs.ai_call_status` (hot/warm/cold/none), written by `mark_crm_update` after wrap-up. It is not in `CALL_CARD_FIELDS` today, so it must be added. It is already in `EVALUATION_FIELDS`, so SIM tenants stay stripped. | call_marking.py:313, :378; routes/calls.py:40-45 |
| Can the browser split channels? | Yes: storage sends `access-control-allow-origin: *`, so Web Audio can read the WAV | `curl -H Origin` on 4bf791b2.wav, 2026-10-18 |

## Architecture Decisions

- **New module `services/call_report.py`.** It holds the report rubric text and `build_report(raw, lines)`,
  which validates every quote with `find_quote` (with a speaker filter) and takes times from lines.
  This keeps call_marking.py from growing; it is already over 500 lines.
- **First valid vote supplies the report**, like `ai_summary`. Quotes that aren't found are dropped.
  The report never touches `checks`, `score` or alerts.
- **A report failure never fails scoring.** A malformed or missing report gives `report = {}`.
- **Raise Step 2 `max_tokens` from 3000 to 6000.** The longer answer must not truncate, because a
  truncated answer fails the whole vote and sinks scoring. The real size is measured at Checkpoint A.
- **`mark_crm_update` already merges** with `{**evaluation, ...}` (call_marking.py:439, :506), so a
  `report` key survives the CRM check. A test pins this.
- **Segments are saved only for stereo calls**, rounded to 0.1 s. `talk` (longest monologue, dead air)
  is computed in `call_metrics` from those segments.
- **Split audio uses Web Audio `ChannelSplitterNode`.** Right channel (index 1) = telecaller, matching
  `TELECALLER_CHANNEL`. With no segments (mono or legacy calls), the plain `<audio>` shows.

### Worked example (data flow for one call)

```
ed296fa2 (51.7s stereo)
 → transcribe_tracks: lines + segments
     telecaller [[0.9,1.6],[4.8,10.9],…]
     customer   [[0.2,0.8],[3.9,4.4],…]
 → call_metrics: longest_monologue = 8.2s · dead_air = 3.4s
 → mark_call: same 3 Gemini votes. Vote 1 also returns
     "report": {"mood":[…], "objections":[…], "promises":[…], "coach":{…}}
 → build_report:
     keep mood @00:30 (quote found on customer track)
     drop a promise whose quote isn't in the transcript
 → evaluation.report = {mood, turning_point, objections, promises, coach, talk, segments}
 → UI:
     Verdict(score, ai_call_status, next_action)
     SplitAudio(segments)
     click "00:30" → audio.currentTime = 30
```

(Numbers above are illustrative. Real ones come from Checkpoint A.)

## Task List

### Phase 1: Backend (data ready, no UI change)
- [x] Task 1: Talk metrics: `longest_monologue`, `dead_air` (pure, TDD)
- [x] Task 2: `call_report.py`: report rubric + `build_report` validation (pure, TDD)
- [x] Task 3: Wire the report into `mark_call` and the pipeline, raise max_tokens, add `ai_call_status` to the call card fields

### Checkpoint A: Backend + AI quality (stop and show numbers)
- [ ] Full `python -m pytest` passes
- [ ] Read-only eval on the 3 stored calls: run `mark_call` on each saved transcript (no DB writes) and report:
  - quotes found vs dropped (target ≥ 80% found)
  - output size vs the 6000 limit
  - any failed votes
  - the 3 coaching tips, verbatim
- [ ] Show the numbers to the user before the UI work

### Phase 2: Frontend
- [x] Task 4: `CallReport` panel: types, pure helpers, and render in CallDetail (verdict, mood, turning point, objections, promises, coach, talk)
- [x] Task 5: `SplitAudio`: channel toggle, speech bars, seek from any timestamp

### Checkpoint B: Complete
- [ ] Frontend `npm run typecheck && npm run lint && npm test` pass
- [ ] UI QA as the UI test tenant (local `make dev-backend` + local frontend):
  - screenshots at 375 and 1440 widths
  - "Telecaller only" isolates one voice
  - legacy call shows plain player, no errors
- [ ] **Ask first:** regenerate one real call's report ("Retry AI" on ed296fa2) on the live DB so the QA has real data
- [ ] /review on the full diff, subsystem-notes.md updated, commit to main. No push until told.

## Who does what

The Opus planner allocates the work and runs `code-review-and-quality` on every worker diff before
showing it.

| Task | Worker | Why |
|---|---|---|
| 1, 2 | Sonnet | Pure logic with tests, exact spec |
| 3 | Planner (Opus) | Touches the scoring pipeline: a wrong move breaks every call's score |
| 4, 5 | Sonnet | UI logic. Design from `frontend-ui-engineering`, Anril tokens |
| Checkpoint test runs | Haiku | Mechanical |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Longer answer truncates, so a vote fails and scoring breaks | High | max_tokens 6000; measure at Checkpoint A; `build_report` failure → `{}`; test that scoring survives a missing or garbage report |
| AI invents quotes or misattributes speakers | Med | `find_quote` with speaker filter; unmatched dropped; ≥80% target measured |
| Report bloats `evaluation`, slowing the review list | Low | Segments rounded to 0.1 s; review route already caps at 50 calls/lead; measure bytes on a 10-min call in tests |
| Gemini cost per call rises | Low | Same 3 requests; only more output tokens. Report the token delta at Checkpoint A |
| Web Audio blocked on some browsers (autoplay rules) | Low | Build the graph on first user Play click; fall back to plain `<audio>` on error |
| Only 3 recordings exist until the TeleCMI renewal | Med | Eval on the 3; full QA after renewal if a fresh call is needed |

## Open Questions

None blocking. The live-DB regeneration at Checkpoint B needs a yes when we get there.
