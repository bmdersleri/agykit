#!/usr/bin/env bash
# Tests for multi-agent orchestrator compatibility:
#   - _detect_agent priority (override > runtime env > installed file > unknown)
#   - _agent_system_file mapping
#   - _architect_invoke builds the correct per-agent CLI invocation
#
# Detection depends on env + HOME-relative files, so each case runs in a clean
# subshell with a fake empty HOME (no agent config on disk) unless the case is
# specifically testing the file-fallback path.
set -uo pipefail

THIS_DIR=$(cd "$(dirname "$0")" && pwd)
AGYKIT="$THIS_DIR/../agykit"

PASS=0; FAIL=0
ok() {
    if eval "$2"; then echo "ok   - $1"; PASS=$((PASS + 1))
    else echo "NOT ok - $1"; FAIL=$((FAIL + 1)); fi
}

# Run _detect_agent in a controlled env. Clears every agent signal first, then
# applies the caller's assignments. Uses an empty HOME so installed-file checks
# don't fire unless the case creates the file. Extra args are `KEY=VAL` exports.
detect_in_env() {
    local fake_home="$1"; shift
    env -i HOME="$fake_home" PATH="$PATH" "$@" \
        bash -c "source '$AGYKIT' 2>/dev/null; _detect_agent"
}

EMPTY_HOME=$(mktemp -d)

# ── Override wins over everything ──
ok "AGYKIT_AGENT=codex overrides" \
    '[ "$(detect_in_env "$EMPTY_HOME" AGYKIT_AGENT=codex CLAUDE_CODE_SESSION_ID=x)" = "codex" ]'
ok "AGYKIT_AGENT=opencode overrides" \
    '[ "$(detect_in_env "$EMPTY_HOME" AGYKIT_AGENT=opencode)" = "opencode" ]'
ok "AGYKIT_AGENT=claude overrides" \
    '[ "$(detect_in_env "$EMPTY_HOME" AGYKIT_AGENT=claude CODEX_SANDBOX=1)" = "claude" ]'
ok "AGYKIT_AGENT garbage is ignored (falls through)" \
    '[ "$(detect_in_env "$EMPTY_HOME" AGYKIT_AGENT=bogus CLAUDE_CODE_SESSION_ID=x)" = "claude" ]'

# ── Runtime env signals ──
ok "CLAUDE_CODE_SESSION_ID -> claude" \
    '[ "$(detect_in_env "$EMPTY_HOME" CLAUDE_CODE_SESSION_ID=abc)" = "claude" ]'
ok "CLAUDE_CODE_ENTRYPOINT -> claude" \
    '[ "$(detect_in_env "$EMPTY_HOME" CLAUDE_CODE_ENTRYPOINT=cli)" = "claude" ]'
ok "CODEX_SANDBOX -> codex" \
    '[ "$(detect_in_env "$EMPTY_HOME" CODEX_SANDBOX=1)" = "codex" ]'
ok "OPENCODE -> opencode" \
    '[ "$(detect_in_env "$EMPTY_HOME" OPENCODE=1)" = "opencode" ]'

# ── Env beats installed files (the core priority fix) ──
# Fake home with BOTH claude creds and codex config, but codex env present.
PRIO_HOME=$(mktemp -d)
mkdir -p "$PRIO_HOME/.claude" "$PRIO_HOME/.codex"
echo '{}' > "$PRIO_HOME/.claude/.credentials.json"
echo '' > "$PRIO_HOME/.codex/auth.json"
ok "runtime env (codex) beats on-disk claude creds" \
    '[ "$(detect_in_env "$PRIO_HOME" CODEX_SANDBOX=1)" = "codex" ]'

# ── Installed-file fallback (no env) ──
CODEX_HOME_DIR=$(mktemp -d); mkdir -p "$CODEX_HOME_DIR/.codex"; echo '' > "$CODEX_HOME_DIR/.codex/auth.json"
ok "no env + ~/.codex/auth.json -> codex" \
    '[ "$(detect_in_env "$CODEX_HOME_DIR")" = "codex" ]'
CLAUDE_HOME_DIR=$(mktemp -d); mkdir -p "$CLAUDE_HOME_DIR/.claude"; echo '{}' > "$CLAUDE_HOME_DIR/.claude/.credentials.json"
ok "no env + ~/.claude creds -> claude" \
    '[ "$(detect_in_env "$CLAUDE_HOME_DIR")" = "claude" ]'
OC_HOME_DIR=$(mktemp -d); mkdir -p "$OC_HOME_DIR/.config/opencode"; echo '{}' > "$OC_HOME_DIR/.config/opencode/opencode.json"
ok "no env + opencode.json -> opencode" \
    '[ "$(detect_in_env "$OC_HOME_DIR")" = "opencode" ]'

# ── Unknown when nothing present ──
ok "no env + empty home -> unknown" \
    '[ "$(detect_in_env "$EMPTY_HOME")" = "unknown" ]'

# ── _agent_system_file mapping + files exist in repo ──
sysfile_for() {
    env -i HOME="$EMPTY_HOME" PATH="$PATH" AGYKIT_AGENT="$1" \
        bash -c "source '$AGYKIT' 2>/dev/null; _agent_system_file"
}
ok "claude -> CLAUDE_AGY_SYSTEM.md"   '[ "$(sysfile_for claude)" = "CLAUDE_AGY_SYSTEM.md" ]'
ok "codex -> CODEX_AGY_SYSTEM.md"     '[ "$(sysfile_for codex)" = "CODEX_AGY_SYSTEM.md" ]'
ok "opencode -> OPENCODE_AGY_SYSTEM.md" '[ "$(sysfile_for opencode)" = "OPENCODE_AGY_SYSTEM.md" ]'
ok "CLAUDE_AGY_SYSTEM.md exists"   '[ -f "$THIS_DIR/../CLAUDE_AGY_SYSTEM.md" ]'
ok "CODEX_AGY_SYSTEM.md exists"    '[ -f "$THIS_DIR/../CODEX_AGY_SYSTEM.md" ]'
ok "OPENCODE_AGY_SYSTEM.md exists" '[ -f "$THIS_DIR/../OPENCODE_AGY_SYSTEM.md" ]'

# ── _architect_invoke builds correct per-agent invocation (stub bins) ──
STUB=$(mktemp -d)
for b in claude codex opencode; do
    cat > "$STUB/$b" <<X
#!/usr/bin/env bash
echo "$b-called: \$*"
X
    chmod +x "$STUB/$b"
done
arch() {
    # $1=AGYKIT_ARCHITECT_ESCALATE, $2=prompt, rest=extra env
    local esc="$1" prompt="$2"; shift 2
    env -i HOME="$EMPTY_HOME" PATH="$STUB:$PATH" AGYKIT_ARCHITECT_ESCALATE="$esc" "$@" \
        bash -c "source '$AGYKIT' 2>/dev/null; _architect_invoke '$prompt'"
}
ok "architect claude -> 'claude -p'" \
    '[ "$(arch claude P)" = "claude-called: -p P" ]'
ok "architect codex -> 'codex exec'" \
    '[ "$(arch codex P)" = "codex-called: exec P" ]'
ok "architect opencode -> 'opencode run'" \
    '[ "$(arch opencode P)" = "opencode-called: run P" ]'
ok "architect opencode + model -> 'run -m'" \
    '[ "$(arch opencode P AGYKIT_ARCHITECT_MODEL=prov/m)" = "opencode-called: run P -m prov/m" ]'
ok "architect auto resolves via detection (codex env)" \
    '[ "$(arch auto P CODEX_SANDBOX=1)" = "codex-called: exec P" ]'
ok "architect empty target -> graceful unavailable" \
    '[[ "$(arch "" P)" == *"Architect unavailable"* ]]'

# ── Tailscale dashboard share helpers ──
TAIL_STUB_DIR=$(mktemp -d)
TAIL_LOG="$TAIL_STUB_DIR/tailscale.log"
cat > "$TAIL_STUB_DIR/tailscale" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$TAIL_LOG"
if [ "\$1" = "ip" ]; then
    echo "100.70.92.41"
fi
EOF
chmod +x "$TAIL_STUB_DIR/tailscale"

share_cmds() {
    env -i HOME="$EMPTY_HOME" PATH="$TAIL_STUB_DIR:$PATH" \
        bash -c "source '$AGYKIT' 2>/dev/null; _dash_tailscale_enable 7373 80; _dash_tailscale_disable 80; _dash_tailscale_remote_url"
}
ok "dash tailscale helper uses serve on port 80" \
    '[[ "$(share_cmds)" = "http://100.70.92.41/" ]] && grep -q -- "serve --bg --yes --http=80 localhost:7373" "$TAIL_LOG" && grep -q -- "serve --yes --http=80 off" "$TAIL_LOG"'

rm -rf "$EMPTY_HOME" "$PRIO_HOME" "$CODEX_HOME_DIR" "$CLAUDE_HOME_DIR" "$OC_HOME_DIR" "$STUB"
rm -rf "$TAIL_STUB_DIR"
echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
