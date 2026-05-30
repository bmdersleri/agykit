#!/usr/bin/env bash
# Unit tests for agykit's snapshot / normalize / rollback git plumbing.
# These guard the do-escalate safety model: user WIP must survive, agy's
# changes must be reverted on failure, stray agy commits must be neutralized.
#
# Run: bash tests/test_git_safety.sh
set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
AGYKIT="$THIS_DIR/../agykit"

# shellcheck source=/dev/null
source "$AGYKIT"      # relies on the dispatch guard at the bottom of agykit
set +e                # agykit enables `set -e`; turn it off so asserts can run

PASS=0; FAIL=0
ok() {
    if eval "$2"; then echo "ok   - $1"; PASS=$((PASS + 1))
    else echo "NOT ok - $1"; FAIL=$((FAIL + 1)); fi
}

newrepo() {
    local d; d=$(mktemp -d)
    cd "$d" || exit 1
    git init -q
    git config user.email t@t.dev
    git config user.name tester
    printf 'base\n' > f.txt
    git add -A; git commit -qm base
    echo "$d"
}

# ── snapshot: captures tracked WIP + untracked, without disturbing the tree ──
newrepo >/dev/null
printf 'user-wip\n' >> f.txt          # tracked WIP (a failing test, say)
printf 'newtest\n'  > new_test.txt    # untracked WIP
BASE=$(git rev-parse HEAD)
SNAP=$(_snapshot)

ok "snapshot keeps tracked WIP in working tree" '[ "$(tail -1 f.txt)" = "user-wip" ]'
ok "snapshot keeps untracked WIP present"       '[ -f new_test.txt ]'
ok "snapshot does not move HEAD"                '[ "$(git rev-parse HEAD)" = "$BASE" ]'
ok "snapshot returns a real commit object"      'git cat-file -e "$SNAP" 2>/dev/null'
ok "snapshot does not stage anything"           '[ -z "$(git diff --cached --name-only)" ]'

# ── normalize: a stray agy commit is undone, changes stay in the tree ──
printf 'agy-change\n' >> f.txt
git commit -qam "agy stray commit"             # simulate agy committing on its own
_normalize_head "$BASE"

ok "normalize returns HEAD to BASE"             '[ "$(git rev-parse HEAD)" = "$BASE" ]'
ok "normalize keeps agy change in tree"         'grep -q agy-change f.txt'
ok "normalize keeps user WIP in tree"           'grep -q user-wip f.txt'

# ── rollback: restores exact pre-run state (agy gone, user WIP intact) ──
printf 'agy-newfile\n' > agy_file.txt          # agy created a new untracked file
_rollback_to "$BASE" "$SNAP"

ok "rollback removes agy tracked change"        '! grep -q agy-change f.txt'
ok "rollback removes agy new file"              '[ ! -f agy_file.txt ]'
ok "rollback restores user tracked WIP"         '[ "$(tail -1 f.txt)" = "user-wip" ]'
ok "rollback restores user untracked WIP"       '[ -f new_test.txt ]'
ok "rollback leaves HEAD at BASE"               '[ "$(git rev-parse HEAD)" = "$BASE" ]'
ok "rollback leaves nothing staged"             '[ -z "$(git diff --cached --name-only)" ]'

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
