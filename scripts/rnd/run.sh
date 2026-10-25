#!/usr/bin/env bash
# Start an unattended R&D run.
#
#   scripts/rnd/run.sh night      quality scouts (errors, conversations, live UI, code health)
#   scripts/rnd/run.sh strategy   the weekly strategy run (.agents/rnd/charter.md)
#   scripts/rnd/run.sh build      build the report items the founder ticked (- [x] Approve)
#   scripts/rnd/run.sh auto       what the nightly Claude desktop task (anril-rnd-nightly, 01:30)
#                                 starts: build, then night; strategy on Sundays
#
# Builds: each ticked item gets its own branch rnd/<report>-<n>-<slug> and worktree
# .worktrees/build-<...>; the agent edits and tests there, then THIS script runs make verify
# and commits to that branch (the agent never touches git). Nothing is merged or pushed:
# the founder does that. Items are tried once (~/.aira-rnd/built.json); untick-and-retick
# does not retry — remove the id from built.json to retry.
#
# Safety: AIRA_AUTONOMOUS=1 switches on scripts/rnd/fence.py (loaded via fence-settings.json,
# regardless of what the worktree contains). The run happens in a dedicated worktree reset
# to the committed local main; reports go to ~/Documents/anril-assets/rnd/reports (outside
# the repo: they can hold aggregated customer patterns). Caps: RND_NIGHT_BUDGET / RND_STRATEGY_BUDGET (USD estimate).
set -euo pipefail

MAIN="$(cd "$(dirname "$0")/../.." && pwd)"
STATE="$HOME/.aira-rnd"
WT="$MAIN/.worktrees/rnd"
OUT="${RND_OUT:-$HOME/Documents/anril-assets/rnd/reports}"
KIND="${1:-auto}"
NIGHT_BUDGET="${RND_NIGHT_BUDGET:-8}"
STRATEGY_BUDGET="${RND_STRATEGY_BUDGET:-20}"
BUILD_BUDGET="${RND_BUILD_BUDGET:-8}"      # per item
BUILD_LIMIT="${RND_BUILD_LIMIT:-2}"        # items per night
MAX_SECONDS="${RND_MAX_SECONDS:-5400}"

export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
mkdir -p "$STATE/logs" "$OUT"
# fence-settings.json names the checkout as __MAIN__; fill it in so the .env deny rules and
# the fence hook follow the repo wherever it lives (a hard-coded path broke on the rename).
FENCE="$STATE/fence-settings.json"
sed "s|__MAIN__|$MAIN|g" "$MAIN/scripts/rnd/fence-settings.json" >"$FENCE"
# The Supabase MCP token lives here (chmod 600, never in git); the nightly task starts this script with a clean env (env -i), so no shell profile.
[ -f "$STATE/env" ] && source "$STATE/env"

notify() { osascript -e "display notification \"$2\" with title \"Aira R&D\" subtitle \"$1\"" >/dev/null 2>&1 || true; }

prepare_worktree() {
  # Local `main` (committed work, pushed or not — never the half-edited working tree).
  # Production itself is checked directly by the scouts (logs, DB, live site).
  git -C "$MAIN" fetch -q origin main || true
  if [ ! -d "$WT/.git" ] && [ ! -f "$WT/.git" ]; then
    git -C "$MAIN" worktree add -q --detach "$WT" main
  else
    git -C "$WT" checkout -q -f --detach main
    git -C "$WT" clean -q -fd -e backend/.venv -e frontend/node_modules
  fi
  link_heavy "$WT"
}

# Heavy or secret files a clean checkout lacks; linked, never copied into git.
LINKED=(backend/.venv frontend/node_modules backend/evals/ui/.test-account.json)
link_heavy() {
  local dir="$1" path
  for path in "${LINKED[@]}"; do
    [ -e "$MAIN/$path" ] && ln -sfn "$MAIN/$path" "$dir/$path"
  done
  return 0
}

# One unattended Claude session inside the fence + sandbox. agent <dir> <model> <budget> <log> <prompt>
agent() {
  local dir="$1" model="$2" budget="$3" log="$4" prompt="$5" rc=0
  (
    cd "$dir"
    export AIRA_AUTONOMOUS=1 AIRA_RND_ROOT="$dir" AIRA_RND_OUT="$OUT"
    caffeinate -dimsu timeout "$MAX_SECONDS" claude -p "$prompt" \
      --model "$model" \
      --max-budget-usd "$budget" \
      --permission-mode bypassPermissions \
      --settings "$FENCE" \
      --add-dir "$OUT" \
      --no-session-persistence
  ) >>"$log" 2>&1 || rc=$?
  return "$rc"
}

# The checks run here, by this script, not by the agent: tests, typecheck, lint and the
# live UI checks (a real browser) need things the agent's sandbox rightly refuses. The
# agent only reads the results and the screenshots.
run_checks() {
  local log="$1" checks="$OUT/checks-$(date +%Y-%m-%d).txt"
  echo "[$(date)] running make verify in the worktree" >>"$log"
  (cd "$WT" && timeout 1800 bash scripts/verify.sh) >"$checks" 2>&1 || true
  echo "[$(date)] checks written to $checks" >>"$log"
}

run_one() {
  local kind="$1" model="$2" budget="$3"
  local log prompt started rc=0
  log="$STATE/logs/$kind-$(date +%Y-%m-%d-%H%M).log"
  prompt="$(cat "$MAIN/.agents/rnd/$kind.md")"
  started="$(mktemp "$STATE/.started.XXXXXX")"
  echo "[$(date)] $kind run starting (model=$model budget=\$$budget)" >>"$log"
  [ "$kind" = "night" ] && run_checks "$log"
  agent "$WT" "$model" "$budget" "$log" "$prompt" || rc=$?
  echo "[$(date)] $kind run finished (exit $rc)" >>"$log"
  # Success means a fresh report exists, not just a clean exit.
  if [ "$rc" -eq 0 ] && [ "$OUT/LATEST-$kind.md" -nt "$started" ]; then
    notify "$kind report ready" "Open anril-assets/rnd/reports/LATEST-$kind.md"
  else
    notify "$kind run needs a look" "Exit $rc, no fresh report. Log: ~/.aira-rnd/logs/$(basename "$log")"
  fi
  rm -f "$started"
}

# Build every newly ticked item (up to BUILD_LIMIT). Writes $OUT/builds-<date>.md, which the
# night report puts first under "Built for you".
run_builds() {
  local log="$STATE/logs/build-$(date +%Y-%m-%d-%H%M).log" items count k
  items="$(mktemp -d "$STATE/.items.XXXXXX")"
  count="$(python3 "$MAIN/scripts/rnd/approved.py" "$OUT" "$STATE/built.json" "$BUILD_LIMIT" "$items")"
  echo "[$(date)] $count approved item(s) to build" >>"$log"
  if [ "$count" -gt 0 ]; then
    mkdir -p "$OUT/build"
    local builds="$OUT/builds-$(date +%Y-%m-%d).md"
    [ -f "$builds" ] || printf '# Built for you — %s\n\nEach item is on its own branch; nothing is merged or pushed.\n' "$(date +%Y-%m-%d)" >"$builds"
    for ((k = 0; k < count; k++)); do
      build_one "$items/item-$k.env" "$items/item-$k.md" "$log" "$builds"
    done
    notify "$count build(s) ready to review" "Open anril-assets/rnd/reports/builds-$(date +%Y-%m-%d).md"
  fi
  rm -rf "$items"
}

build_one() {
  local envfile="$1" itemfile="$2" log="$3" builds="$4"
  local ITEM_ID ITEM_TITLE ITEM_BRANCH ITEM_SAFE
  source "$envfile"
  local wtb="$MAIN/.worktrees/build-$ITEM_SAFE" summary="$OUT/build/$ITEM_SAFE.md"
  local verify="$OUT/build/$ITEM_SAFE-verify.txt" status commit="no code change" result="not run"
  echo "[$(date)] building $ITEM_ID on $ITEM_BRANCH" >>"$log"
  mark_built "$ITEM_ID"   # tried once, whatever happens next
  if git -C "$MAIN" show-ref --quiet --verify "refs/heads/$ITEM_BRANCH"; then
    printf '\n### %s\n- Skipped: branch `%s` already exists.\n' "$ITEM_TITLE" "$ITEM_BRANCH" >>"$builds"
    return 0
  fi
  git -C "$MAIN" worktree add -q -b "$ITEM_BRANCH" "$wtb" main
  link_heavy "$wtb"
  local prompt
  prompt="$(cat "$MAIN/.agents/rnd/build.md")

## The approved item
ID: $ITEM_ID
BRANCH (the runner commits to it): $ITEM_BRANCH
SUMMARY (write it here): $summary

$(cat "$itemfile")"
  agent "$wtb" opus "$BUILD_BUDGET" "$log" "$prompt" || echo "[$(date)] builder exited non-zero" >>"$log"
  status="$( (grep -m1 -E '^Status:' "$summary" 2>/dev/null || true) | sed 's/^Status:[[:space:]]*//')"
  if ! git -C "$wtb" diff --quiet || [ -n "$(git -C "$wtb" ls-files --others --exclude-standard -- . "${LINKED[@]/#/:(exclude)}")" ]; then
    (cd "$wtb" && VERIFY_SKIP="ui-live evals" timeout 1800 bash scripts/verify.sh) >"$verify" 2>&1 || true
    result="$( (grep -m1 '^RESULT:' "$verify" || echo "RESULT: no result line") | sed 's/^RESULT:[[:space:]]*//')"
    commit="$(commit_build "$wtb" "$summary" "$ITEM_ID" "$ITEM_TITLE" "$result")"
  fi
  {
    printf '\n### %s\n' "$ITEM_TITLE"
    printf -- '- Item: %s · Status: **%s**\n' "$ITEM_ID" "${status:-no summary written}"
    printf -- '- Branch: `%s` · Commit: %s\n' "$ITEM_BRANCH" "$commit"
    printf -- '- make verify on the branch: **%s** (`build/%s-verify.txt`)\n' "$result" "$ITEM_SAFE"
    printf -- '- What the builder says: `build/%s.md`\n' "$ITEM_SAFE"
    printf -- '- Accept: `git merge --no-ff %s` then push · Drop: `git worktree remove .worktrees/build-%s && git branch -D %s`\n' "$ITEM_BRANCH" "$ITEM_SAFE" "$ITEM_BRANCH"
  } >>"$builds"
}

# The builder never touches git: this commits its working tree to its own branch only.
commit_build() {
  local wtb="$1" summary="$2" id="$3" title="$4" result="$5" msg
  git -C "$wtb" add -A -- . "${LINKED[@]/#/:(exclude)}"
  if git -C "$wtb" diff --cached --quiet; then echo "no code change"; return 0; fi
  msg="$(awk '/^COMMIT_MESSAGE:/{f=1;next} /^END_COMMIT_MESSAGE/{f=0} f' "$summary" 2>/dev/null)"
  [ -n "$msg" ] || msg="rnd: $title"
  if git -C "$wtb" commit -q -m "$msg" -m "Built unattended by the Aira R&D builder for $id (make verify: $result).
Review before merging; nothing was pushed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" >>"$STATE/logs/commit.log" 2>&1; then
    git -C "$wtb" rev-parse --short HEAD
  else
    echo "commit FAILED (pre-commit hook?) — changes left uncommitted in the worktree"
  fi
}

mark_built() {
  python3 - "$STATE/built.json" "$1" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); done = json.loads(p.read_text()) if p.exists() else []
if sys.argv[2] not in done: done.append(sys.argv[2])
p.write_text(json.dumps(done, indent=1))
PY
}

main() {
  # One run at a time (mkdir is atomic; macOS has no flock).
  if ! mkdir "$STATE/run.lock" 2>/dev/null; then
    echo "another R&D run is in progress (remove $STATE/run.lock if stale)" >&2; exit 0
  fi
  trap 'rmdir "$STATE/run.lock" 2>/dev/null' EXIT
  command -v timeout >/dev/null || timeout() { shift; "$@"; }
  prepare_worktree
  case "$KIND" in
    night)    run_one night sonnet "$NIGHT_BUDGET" ;;
    strategy) run_one strategy opus "$STRATEGY_BUDGET" ;;
    build)    run_builds ;;
    auto)
      run_builds
      run_one night sonnet "$NIGHT_BUDGET"
      if [ "$(date +%u)" = "7" ]; then run_one strategy opus "$STRATEGY_BUDGET"; fi ;;
    *) echo "usage: $0 night|strategy|build|auto" >&2; exit 2 ;;
  esac
}

main
