#!/usr/bin/env bash
# Tests for Codex compatibility: CLI command, agent detection, skill files.
set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
AGYKIT="$THIS_DIR/../agykit"
source "$AGYKIT"
set +e

PASS=0; FAIL=0
ok() {
    if eval "$2"; then echo "ok   - $1"; PASS=$((PASS + 1))
    else echo "NOT ok - $1"; FAIL=$((FAIL + 1)); fi
}

# ── _detect_agent() ──
AGENT=$(_detect_agent)
ok "detect agent returns a known value" \
    '[[ "$AGENT" =~ ^(claude|codex|opencode|unknown)$ ]]'

# ── _agent_system_file() ──
SYSFILE=$(_agent_system_file)
ok "agent system file is non-empty" '[ -n "$SYSFILE" ]'
ok "agent system file has .md extension" '[[ "$SYSFILE" == *.md ]]'

# ── agykit codex (graceful when no codex data) ──
CODEX_OUT=$(AGYKIT_DASH_CODEX_HOME=/nonexistent "$AGYKIT" codex 2>&1)
ok "agykit codex runs without crash" '[ $? -eq 0 ]'

# ── agykit codex --json (valid JSON) ──
CODEX_JSON=$(AGYKIT_DASH_CODEX_HOME=/nonexistent "$AGYKIT" codex --json 2>&1)
ok "agykit codex --json is valid JSON" \
    'echo "$CODEX_JSON" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null'

# ── agykit codex --status (one-line) ──
CODEX_STAT=$("$AGYKIT" codex --status 2>&1)
ok "agykit codex --status produces output" '[ -n "$CODEX_STAT" ]'

# ── Skill files exist in project ──
ok "skills/codex.md exists" '[ -f "$THIS_DIR/../skills/codex.md" ]'
ok "skills/SKILL.md exists" '[ -f "$THIS_DIR/../skills/SKILL.md" ]'
ok "skills/agykit.md exists" '[ -f "$THIS_DIR/../skills/agykit.md" ]'
ok "skills/opencode.md exists" '[ -f "$THIS_DIR/../skills/opencode.md" ]'

# ── Install script references all skill files ──
ok "install.sh references codex skill" \
    'grep -q "skills/codex.md" "$THIS_DIR/../install.sh"'
ok "install.sh references SKILL.md" \
    'grep -q "skills/SKILL.md" "$THIS_DIR/../install.sh"'
ok "install.sh references opencode skill" \
    'grep -q "skills/opencode.md" "$THIS_DIR/../install.sh"'

# ── Codex detection (env-forced, isolated) ──
CODEX_DETECT=$(env -i HOME=/nonexistent PATH="$PATH" AGYKIT_AGENT=codex \
    bash -c "source '$AGYKIT' 2>/dev/null; _detect_agent")
ok "codex detected via AGYKIT_AGENT override" '[ "$CODEX_DETECT" = "codex" ]'

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
