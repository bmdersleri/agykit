#!/usr/bin/env bash
# Smoke tests: every registered CLI command runs without crash.
set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
AGYKIT="$THIS_DIR/../agykit"

PASS=0; FAIL=0
ok() {
    if eval "$2"; then echo "ok   - $1"; PASS=$((PASS + 1))
    else echo "NOT ok - $1"; FAIL=$((FAIL + 1)); fi
}

# Commands that should succeed (exit 0)
ok "agykit help"                  '"$AGYKIT" help >/dev/null 2>&1'
ok "agykit --help"                '"$AGYKIT" --help >/dev/null 2>&1'
ok "agykit version"               '"$AGYKIT" version >/dev/null 2>&1'
ok "agykit whoami"                '"$AGYKIT" whoami >/dev/null 2>&1'
ok "agykit models"                '"$AGYKIT" models >/dev/null 2>&1'
ok "agykit model"                 '"$AGYKIT" model >/dev/null 2>&1'
ok "agykit account-list"          '"$AGYKIT" account-list >/dev/null 2>&1'
ok "agykit status"                '"$AGYKIT" status >/dev/null 2>&1'
ok "agykit rtk"                   '"$AGYKIT" rtk >/dev/null 2>&1'
ok "agykit rtk --json"            '"$AGYKIT" rtk --json >/dev/null 2>&1'
ok "agykit log"                   '"$AGYKIT" log >/dev/null 2>&1'
ok "agykit log 5"                 '"$AGYKIT" log 5 >/dev/null 2>&1'
ok "agykit jobs"                  '"$AGYKIT" jobs >/dev/null 2>&1'
ok "agykit stats"                 '"$AGYKIT" stats >/dev/null 2>&1'
ok "agykit quota --status"        '"$AGYKIT" quota --status >/dev/null 2>&1'
ok "agykit dash --status"         '"$AGYKIT" dash --status >/dev/null 2>&1'

# JSON output validity
ok "agykit rtk --json valid"      '"$AGYKIT" rtk --json 2>/dev/null | python3 -c "import json,sys; json.load(sys.stdin)"'
ok "agykit jobs --json valid"     '"$AGYKIT" jobs --json 2>/dev/null | python3 -c "import json,sys; json.load(sys.stdin)"'

# Commands that may fail gracefully (exit non-zero is OK, just shouldn't crash)
ok "agykit doctor (no crash)"     '"$AGYKIT" doctor >/dev/null 2>&1; true'
ok "agykit quota (no crash)"      '"$AGYKIT" quota >/dev/null 2>&1; true'

# Unknown command
ok "agykit nonexistent (exit 1)"  '! "$AGYKIT" nonexistent >/dev/null 2>&1'

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
