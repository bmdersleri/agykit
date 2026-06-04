#!/usr/bin/env bash
# Integration tests for `agykit wait` — the scriptable job-completion gate.
#
# Contract under test:
#   succeeded job → exit 0
#   failed job    → exit 1
#   still-running → exit 2 once --timeout elapses (and the live job is NOT
#                   auto-recovered by the wait loop's recovery sweep)
#   bare `wait`   → resolves the most-recent job
#
# Jobs are created directly via the collectors API into an isolated state dir so
# the suite never touches real jobs.
set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$THIS_DIR/.." && pwd)
AGYKIT="$REPO/agykit"

STATE=$(mktemp -d)
FAKE_HOME=$(mktemp -d)
# Isolation: agykit mirrors the primary state dir (~/.gemini) into
# AGYKIT_STATE_DIR on every open, clobbering it. Pointing HOME at an empty dir
# makes the primary empty, so our state dir stays clean and holds only the jobs
# this suite creates.
export HOME="$FAKE_HOME"
export AGYKIT_STATE_DIR="$STATE"
export AGYKIT_JOB_TIMEOUT=""  # disable the hard ceiling for these tests

PASS=0; FAIL=0
ok() {
    if eval "$2"; then echo "ok   - $1"; PASS=$((PASS + 1))
    else echo "NOT ok - $1"; FAIL=$((FAIL + 1)); fi
}

# Create a job in a given terminal/active state; echo its job_id.
# args: <command> <prompt> <status> [owner_pid]
mkjob() {
    PYTHONPATH="$REPO" AGYKIT_STATE_DIR="$STATE" python3 - "$@" <<'PY'
import sys
from dashboard.collectors import jobs
cmd, prompt, status = sys.argv[1], sys.argv[2], sys.argv[3]
owner = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None
jid = jobs.job_create(cmd, prompt, owner)
if status == "succeeded":
    jobs.job_event(jid, "verify_passed", "succeeded", "done")
elif status == "failed":
    jobs.job_event(jid, "job_failed", "failed", "exhausted", "", "", "boom")
elif status == "running":
    jobs.job_event(jid, "account_selected", "running", "x")
print(jid)
PY
}

# succeeded → exit 0
JID=$(mkjob run ok-job succeeded)
ok "wait succeeded → exit 0" '"$AGYKIT" wait "'"$JID"'" --timeout 5 >/dev/null 2>&1'

# failed → exit 1
JID=$(mkjob run bad-job failed)
ok "wait failed → exit 1" '"$AGYKIT" wait "'"$JID"'" --timeout 5 >/dev/null 2>&1; [ $? -eq 1 ]'

# running with live owner → exit 2 after timeout; job stays running
JID=$(mkjob do-escalate live-job running "$$")
"$AGYKIT" wait "$JID" --timeout 2 --interval 1 >/dev/null 2>&1
ok "wait running → exit 2 (timeout)" '[ $? -eq 2 ]'
ok "live job survived wait sweep" \
    'PYTHONPATH="'"$REPO"'" AGYKIT_STATE_DIR="'"$STATE"'" python3 -c "from dashboard.collectors.jobs import job_snapshot; import sys; sys.exit(0 if job_snapshot(\"'"$JID"'\")[\"status\"]==\"running\" else 1)"'

# bare wait resolves most-recent job (the running one above is newest unless a
# newer terminal job is created; make a fresh succeeded job to be the newest)
JID=$(mkjob run newest succeeded)
ok "bare wait → most-recent → exit 0" '"$AGYKIT" wait --timeout 5 >/dev/null 2>&1'

rm -rf "$STATE" "$FAKE_HOME"
echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
