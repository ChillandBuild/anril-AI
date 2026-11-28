# Aira AI — convenience targets

.PHONY: second-brain-close doctor verify rnd-night rnd-strategy rnd-build rnd-dashboard dev-backend

# Session-end second-brain health check (dead links, credential scan, generated-artifact
# git churn, hook liveness, stale .agents/ claims). Read-only. Same script every project
# scaffolded with bootstrapping-second-brain uses — see scripts/second_brain_close.py.
second-brain-close:
	python3 scripts/second_brain_close.py

# Check for a partially-destroyed dev environment (antivirus quarantine has
# deleted individual files out of the stdlib, site-packages, and node_modules
# on this project before). Run when imports fail in ways that make no sense.
# Uses the CURRENT interpreter on purpose — run it from the venv you suspect.
doctor:
	python scripts/check_env_integrity.py

# One answer to "is it really done?": backend tests, frontend typecheck + lint, the R&D
# fence tests, read-only live UI checks as the test account, and AI evals when a TEST key
# tenant is set. PASS / FAIL / SKIPPED per stage. See scripts/verify.sh.
verify:
	bash scripts/verify.sh

# The unattended R&D team (report-only). Normally started at 01:30 by the Claude desktop scheduled task anril-rnd-nightly; these run it now.
rnd-night:
	bash scripts/rnd/run.sh night

rnd-strategy:
	bash scripts/rnd/run.sh strategy

rnd-build:
	bash scripts/rnd/run.sh build

# Local R&D dashboard (127.0.0.1 only): approve, review builds, merge / drop / push, run now.
rnd-dashboard:
	python3 scripts/rnd/dashboard.py

# Safe local backend start: scheduler PAUSED, outbound DRY-RUN, live Supabase DB.
dev-backend:
	bash scripts/dev-backend.sh
