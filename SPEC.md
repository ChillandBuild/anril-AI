# Spec: Call Report v1 (manager-only)

Status: DRAFT, awaiting approval (2026-10-18)

## Objective

Give a manager one page per TeleCMI call that shows, in about 30 seconds, where the sale was won or lost
and what to coach. It extends the existing Notes → Review page; it does not add a new page.

**User:** anyone who already sees Notes → Review: the owner, or a role with `team.manage`. This is
already enforced on both sides (NotesGate.tsx; `require_permission("team.manage")` in
routes/call_review.py). Telecallers see nothing new in v1.

**Why:** to coach telecallers and lift conversions.

**Worked example.** Telecaller Priya calls lead Karthik about a course. The call lasts 4:12 and Karthik
doesn't buy. The manager opens Notes → Review → Karthik → this call and sees:

```
VERDICT     62/100 · Warm · Next: send fee details (Fri 5pm)
AUDIO       [Both | Priya only | Karthik only]   ▶ ━━━━━━━━━━━━━━━━━━
            Priya   ▮▮ ▮▮▮   ▮▮▮▮▮▮      ▮▮▮   ▮▮
            Karthik   ▮   ▮▮   ▮  ▮▮▮▮▮▮    ▮▮
MOOD        🙂 0:20 ── 🙂 1:05 ── 😐 2:10 ── 😠 2:40 ── 😐 3:30
TURNING PT  2:40 ▼ went cold: "fees romba jaasthi" (fee is too high). Priya moved on without answering.
OBJECTIONS  2:40 Fee too high ............ ✗ dodged
            3:30 Must ask parents ........ ✓ handled (callback set)
TALK        Priya 71% · 3 interruptions · longest monologue 0:48 · dead air 0:22
PROMISES    1:50 "10% discount tharen" (I'll give 10% off) ⚠ not in knowledge base
COACH       At 2:40, answer the fee question with EMI options before moving on.
```

Every timestamp is clickable and seeks the audio to that moment.

### Acceptance criteria

1. **Verdict.** Shows the score, lead temperature (hot/warm/cold from the CRM check), and the next step
   with its date (ai_summary.next_action, next_action_at). All of these exist today; the report only
   gathers them in one place.
2. **Mood line.** Shows 3–8 moments of the lead's mood (positive / neutral / negative). Each has a quote
   that `find_quote` found on the **customer** track, and its time comes from that line, never from the AI.
3. **Turning point.** At most one, with quote, time, direction (warmed / cooled) and a one-line reason.
   It is omitted when the AI names none or the quote isn't found.
4. **Objections.** Each objection has a quote and time (customer track), plus a handling verdict
   (`handled | partly | dodged`) with a one-line reason.
5. **Split audio.** A three-way toggle (Both / Telecaller only / Lead only) plays one channel of the
   existing stereo recording in the browser. Speech bars per side come from the saved speech segments.
   Clicking a bar or any timestamp seeks there. For mono or legacy calls (no segments saved), only the
   plain player shows.
6. **Talk balance.** Talk % and interruptions (existing), plus two new figures computed by code, not AI:
   - longest telecaller monologue: the longest continuous run of telecaller speech, merging gaps
     under 1.5 s
   - dead air: total time when neither side speaks, counting only gaps of 3 s or more, and only after
     the first speech
7. **Promises.** Each telecaller promise (discount, guarantee, refund, timeline, freebie) has a quote and
   time. It is flagged ⚠ risky when the knowledge base doesn't support it.
8. **Coaching tip.** Exactly one tip: one sentence, tied to a timestamped quote.
9. **No second AI call.** The new fields come from the existing Step 2 (call_marking) prompt. The number
   of AI requests per call stays the same.
10. **Graceful gaps.**
    - Early-exit calls, failed calls and calls scored before this ships show today's view plus whatever
      report parts exist; they never show an error.
    - "Retry AI" on an old call regenerates its report.
11. **SIM tenants** still see no evaluation. The report lives inside `evaluation`, which
    `strip_evaluation` already removes.

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Where the AI fields come from | Extend the Step 2 rubric/output in call_marking.py | Step 2 already sees the KB (needed for risky promises) and runs only on real conversations (early-exit calls have nothing to coach). Same request, so no extra cost per call; only a longer prompt and answer. |
| Voting on the new fields | Taken from the first valid vote, like `ai_summary` today; every quote must pass `find_quote` or it is dropped | They're display-only and never change the score. Voting on lists of moods is fuzzy; quote validation is the real guard against made-up lines. |
| Storage | New key `evaluation.report` (JSON) | Adding keys inside `evaluation` is safe (evaluation_version stays 4). No migration. Already stripped for SIM tenants. |
| Speech segments | Saved as `evaluation.report.segments = {telecaller: [[s,e],…], customer: [[s,e],…]}`, rounded to 0.1 s | Needed for the bars and the new metrics. Today they're computed then thrown away. A 10-minute call is roughly a few hundred pairs, a few KB. |
| Split audio | Browser Web Audio `ChannelSplitterNode` on the existing recording_url | No new files and no storage cost. Right channel = telecaller (`TELECALLER_CHANNEL = 1`). |
| Full transcript | **Not shown.** Only timestamped quotes are clickable | Keeps the current privacy rule ("full transcript never sent to the browser", call_transcript.py). The recording is the evidence. See Open Question 1. |
| Telecaller visibility | None in v1 | Agreed in the interview. |

### Shape of `evaluation.report`

```json
{
  "report_version": 1,
  "mood": [{"time": "02:40", "start": 160, "mood": "negative", "quote": "fees romba jaasthi"}],
  "turning_point": {"time": "02:40", "start": 160, "direction": "cooled",
                    "quote": "fees romba jaasthi", "why": "Fee question not answered"},
  "objections": [{"time": "02:40", "start": 160, "quote": "...", "handling": "dodged", "why": "..."}],
  "promises": [{"time": "01:50", "start": 110, "quote": "...", "risky": true, "why": "No discount in KB"}],
  "coach": {"time": "02:40", "start": 160, "quote": "...", "tip": "Answer fee with EMI options first."},
  "talk": {"longest_monologue_s": 48.0, "dead_air_s": 22.0},
  "segments": {"telecaller": [[0.4, 2.1]], "customer": [[2.6, 3.9]]}
}
```

`segments` and `talk` are present only for stereo calls. For example, a mono call's report has no
`segments` key, and the UI falls back to the plain player.

## Tech Stack

- Backend: Python / FastAPI, Gemini via `gemini_analysis_json` (`gemini-3.1-flash-lite`), Supabase. No new
  dependencies.
- Frontend: Next.js / TypeScript / Tailwind, Anril tokens (teal #038285, navy #0A1528). Web Audio API
  (built into the browser). No new dependencies.

## Commands

```
Backend tests:   cd backend && python -m pytest
Targeted:        cd backend && python -m pytest tests/test_call_marking.py tests/test_call_metrics.py tests/test_call_ai_pipeline.py -q
Local backend:   make dev-backend          # never plain uvicorn (shares the live DB)
Frontend:        cd frontend && npm run typecheck && npm run lint && npm test
Local UI:        cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Project Structure (files expected to change)

```
backend/app/services/call_marking.py     → rubric + output schema + parse/validate report fields
backend/app/services/call_metrics.py     → longest_monologue(), dead_air() (pure functions)
backend/app/services/call_ai_pipeline.py → save segments + talk + report into evaluation.report
backend/app/services/call_report.py      → NEW: validate AI report fields via find_quote (keeps call_marking small)
backend/tests/test_call_report.py        → NEW
backend/tests/test_call_metrics.py       → new metric cases
backend/tests/test_call_ai_pipeline.py   → report persisted; mono → no segments
frontend/lib/api.ts                      → types for evaluation.report (+ fix missing ai_summary keys)
frontend/components/CallReport.tsx       → NEW: verdict, mood line, objections, promises, coach, talk
frontend/components/SplitAudio.tsx       → NEW: channel toggle, speech bars, seek(start)
frontend/lib/call-report.ts (+ .test.ts) → NEW: pure helpers (format, bar layout) for vitest (node env)
frontend/app/dashboard/notes/review/CallReview.tsx → swap <audio> + add <CallReport> in CallDetail
```

## Code Style

Follow the existing call_* modules: small pure functions, constants in `scoring_rules`, quotes always
through `find_quote`, the AI never does arithmetic.

```python
def longest_monologue(segments: list[Segment], max_gap: float = MONOLOGUE_GAP_S) -> float:
    """Longest stretch of telecaller speech, treating gaps under max_gap as one run."""
    best = run_start = run_end = 0.0
    for start, end in segments:
        if start - run_end > max_gap:
            run_start = start
        run_end = end
        best = max(best, run_end - run_start)
    return round(best, 1)
```

## Testing Strategy

- **Backend (pytest, TDD).**
  - Metric functions: empty input, single segment, gap merging, dead air only counted after the first
    speech.
  - Report validation: a quote not found is dropped; a speaker mismatch is dropped; time comes from
    the line; caps at 8 mood points and 1 tip.
  - Pipeline: the report is saved; a mono call has no segments; the AI omitting the report doesn't
    fail scoring.
  - Mocked Gemini responses, as in the existing tests.
- **Frontend (vitest, node env).** Pure helpers in lib/call-report.ts. Components are checked by
  typecheck + lint.
- **UI QA.** Render the report as the UI test tenant via `make dev-backend` + local frontend, on one
  regenerated real call (Retry AI on ed296fa2 or a new call after the TeleCMI renewal). Look at
  screenshots at 375 and 1440 widths, and check the channel toggle actually isolates one voice.
- **AI quality check (time-boxed).** Run the new prompt on the 3 stored calls. Count quotes found
  versus dropped, and read the tips. Show the numbers before shipping.

## Boundaries

- **Always:**
  - every AI quote goes through `find_quote` with a speaker filter
  - times come from transcript lines
  - new numbers are computed in `call_metrics`
  - run the targeted tests + full pytest + frontend typecheck/lint before commit
  - commit to main
- **Ask first:**
  - any DB migration or new column (none planned)
  - showing the full transcript
  - changing score logic or the 10 checks
  - adding a second AI call
  - adding dependencies
  - pushing or deploying
- **Never:**
  - let the report change `score`
  - break `evaluation_version == 4` consumers (mark_crm_update, CallAiDetail)
  - show evaluation to SIM tenants
  - expose the report to telecaller-only roles
  - run plain uvicorn locally

## Success Criteria

- On a regenerated real call, the manager view shows all 8 report parts, or cleanly hides the ones
  with no data.
- On the 3 stored calls, at least 80% of AI quotes in the report are found by `find_quote`. Measured
  and shown.
- The AI request count per call is unchanged, and Step 2 still finishes within its current
  max_tokens / retry budget. If not, raise max_tokens and say so.
- "Telecaller only" playback contains no lead voice (manual listen on ed296fa2).
- Full backend suite passes; frontend typecheck, lint and vitest pass.

## Open Questions

1. **Full transcript for managers?** The default is no: only clickable quotes, keeping the current
   privacy rule. A full clickable transcript is easy to add for `team.manage` users if you want it.
2. **Lead temperature source.** I plan to read the CRM check's `customer` (hot/warm/cold). If that isn't
   persisted where the UI can read it, I'll fall back to the lead's current segment. To confirm during
   planning.
3. **CORS on the recording URL.** Web Audio channel splitting needs the Supabase public storage URL to
   allow cross-origin reads. To verify in build. The fallback is to proxy through the backend.
