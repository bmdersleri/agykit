#!/usr/bin/env bash
# Integration tests for `agykit do-escalate`'s safety contract.
#
# Uses a stub agy (AGY_BIN) and monkeypatches the keyring/model functions after
# sourcing, so the REAL orchestration + git plumbing run without a live agy or
# Google account.
#
# Contract under test:
#   success → keep user WIP + agy change, neutralize any stray agy commit
#   failure → restore exact pre-run tree (agy change gone, user WIP intact)
#
# Run: bash tests/test_do_escalate.sh
set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
AGYKIT="$THIS_DIR/../agykit"

# shellcheck source=/dev/null
source "$AGYKIT"
set +e

# Monkeypatch env-coupled functions (legit: they need keyring/settings we lack).
cmd_model()          { :; }
cmd_account_switch() { return 0; }

# Stub agy: makes a "fix", then tries to commit on its own (must be neutralized).
FAKE_AGY=$(mktemp); cat > "$FAKE_AGY" <<'AGY'
#!/usr/bin/env bash
printf 'agy-edit\n' >> src.txt
git add -A >/dev/null 2>&1
git commit -qm "agy stray commit" >/dev/null 2>&1
echo "agy done"
AGY
chmod +x "$FAKE_AGY"
export AGY_BIN="$FAKE_AGY"

PASS=0; FAIL=0
ok() {
    if eval "$2"; then echo "ok   - $1"; PASS=$((PASS + 1))
    else echo "NOT ok - $1"; FAIL=$((FAIL + 1)); fi
}

setup_repo() {
    local d; d=$(mktemp -d); cd "$d" || exit 1
    git init -q; git config user.email t@t.dev; git config user.name tester
    printf 'base\n' > src.txt; git add -A; git commit -qm base
    # user WIP: tracked edit + untracked file (e.g. a freshly written failing test)
    printf 'user-wip\n' >> src.txt
    printf 'wip\n' > wip_test.txt
    # fake agy settings + one account so do-escalate proceeds
    AGY_SETTINGS="$d/settings.json"; printf '{"model":"x"}\n' > "$AGY_SETTINGS"
    ACCOUNTS_DIR="$d/accounts"; mkdir -p "$ACCOUNTS_DIR"; : > "$ACCOUNTS_DIR/t@acct.json"
    echo "$d"
}

# ── SUCCESS: verify needs BOTH agy change and user WIP visible ──
setup_repo >/dev/null
BASE=$(git rev-parse HEAD)
VERIFY_CMD='grep -q agy-edit src.txt && grep -q user-wip src.txt'
cmd_do_escalate "make it pass" >/tmp/esc_ok.log 2>&1
rc=$?
ok "success: exit 0"                         '[ "$rc" -eq 0 ]'
ok "success: stray agy commit neutralized"   '[ "$(git rev-parse HEAD)" = "$BASE" ]'
ok "success: user tracked WIP kept"          'grep -q user-wip src.txt'
ok "success: user untracked WIP kept"        '[ -f wip_test.txt ]'
ok "success: agy change kept"                'grep -q agy-edit src.txt'
ok "success: changes left uncommitted"       '[ -n "$(git status --porcelain)" ]'

# ── FAILURE: verify can never pass → agy work rolled back, WIP survives ──
setup_repo >/dev/null
BASE=$(git rev-parse HEAD)
VERIFY_CMD='false'
cmd_do_escalate "cannot pass" >/tmp/esc_fail.log 2>&1
rc=$?
ok "failure: nonzero exit"                   '[ "$rc" -ne 0 ]'
ok "failure: agy change rolled back"         '! grep -q agy-edit src.txt'
ok "failure: user tracked WIP restored"      'grep -q user-wip src.txt'
ok "failure: user untracked WIP restored"    '[ -f wip_test.txt ]'
ok "failure: HEAD back at BASE"              '[ "$(git rev-parse HEAD)" = "$BASE" ]'

rm -f "$FAKE_AGY"
echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
