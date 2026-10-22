# Execution handoff prompt — paste this to the executing model

You are implementing three related pieces of work in the Aira AI repo (`ChillandBuild/anril-AI`). Read in this order before writing any code:

1. `docs/superpowers/specs/2026-08-23-nested-packages-and-settings-nav-design.md` — the design and *why*. Read the whole thing once, don't skim.
2. `docs/superpowers/plans/2026-08-24-settings-navigation-restructure.md` — plan A.
3. `docs/superpowers/plans/2026-08-24-nested-intake-packages.md` — plan B, including its Task 10 (tap UI / buttons / list messages).

## Execution order — this is not optional

**Plan A (settings navigation restructure) first, start to finish, all 9 tasks.** Plan B's Task 8 explicitly depends on Plan A's Task 6 (`/dashboard/settings/intake-config/page.tsx` must exist first). Do not interleave the two plans.

**Within Plan B, do Task 10 last**, after Tasks 1-9. Task 10 edits code that Tasks 5 and 8 create (`_finalize_leaf`, the `offer_pending`/`awaiting_package_choice` blocks, `PackageEditor.tsx`) — it cannot go first.

## Before you write a single line

Run this and read the output — a teammate (`keerthi-sarav`) actively pushes to this repo's `main`, and both plans have already needed patching once this session because of files they touched mid-session:

```bash
git log --author=keerthi-sarav --oneline -15
git log --author=keerthi-sarav --name-only --since="3 days ago" | grep -v "^$"
ls backend/supabase/migrations | tail -5
```

If any file a plan task is about to touch, or any migration number a plan claims (currently `186_intake_nested_packages.sql`), has moved since these plans were written — **stop and report it, do not silently renumber or reroute and continue.** The person who reads your work needs to know a plan assumption broke, not discover it in review.

## Rules while executing

- **Every step in these plans has real, complete code — that was deliberate.** If what you find in the actual file doesn't match a plan's "old code" quote (different line numbers, slightly different content), stop and report the mismatch rather than guessing which version is current and improvising a fix.
- **Run every test step for real.** Both plans are written TDD-style (write failing test → run it → confirm it fails for the stated reason → implement → run again → confirm pass). Don't write the test and implementation in the same breath and skip the "confirm it fails" step — that step is what catches a test that can't actually fail, which is a worthless test.
- **Task 5 Step 1 of Plan B is a genuine open discovery step**, not filled in on purpose: check which existing test file already exercises `route_intake` end-to-end and copy its exact mocking shape. Don't invent a different mock pattern than what the rest of this codebase's tests use for that function.
- **Task 10 Step 16 of Plan B will likely require you to update assertions Task 5 wrote**, because the `NESTED_PACKAGES` test fixture's names are short enough to trigger the new buttons tier. This is called out in the plan already — don't be surprised by it, don't skip it.
- **Commit after each task**, using the commit messages the plans specify (or close to them). Small commits make the audit pass faster and make it possible to bisect if something's wrong.
- **Don't add anything the plans don't ask for.** No extra refactors, no "while I'm here" cleanups, no new abstractions. If you spot a real problem outside scope, note it in your final report instead of fixing it.
- **Global Constraints sections at the top of each plan are binding** (no new npm/pip dependencies, existing test style, etc.) — they apply to every task even when a task's own section doesn't repeat them.

## When you're done

Report back:
- Which tasks completed, which (if any) you stopped on and why.
- Any plan assumption that turned out to be wrong when you actually touched the file (line numbers, function signatures, anything).
- The actual test output for each task's test-run steps — not a summary claim that "tests pass," the real command output.
- Anything you deliberately deviated from the plan on, and why.

Claude (this session) will review the diff and the test output afterward before anything gets pushed — that review is the real quality gate, not a formality, so don't polish over uncertainty in your report. State plainly what you're not sure about.
