#!/usr/bin/env bash
# agykit uninstaller — removes the symlink. Leaves ~/.gemini/accounts and
# per-project .agykit.conf untouched (your data/config).
set -euo pipefail

TARGET_DIR="${AGYKIT_PREFIX:-$HOME/.local/bin}"
TARGET="$TARGET_DIR/agykit"

if [ -L "$TARGET" ] || [ -f "$TARGET" ]; then
    rm -f "$TARGET"
    echo "Removed: $TARGET"
else
    echo "Not installed at $TARGET (nothing to remove)."
fi

AGENTS_SKILL_DIR="$HOME/.agents/skills/agykit"
if [ -f "$AGENTS_SKILL_DIR/SKILL.md" ]; then
    rm -f "$AGENTS_SKILL_DIR/SKILL.md"
    rmdir "$AGENTS_SKILL_DIR" 2>/dev/null || true
    echo "Removed: opencode skill ($AGENTS_SKILL_DIR)"
fi

echo "Left intact: ~/.gemini/accounts/ (snapshots), .agykit.conf (project config)."
echo "To purge account snapshots: rm -rf ~/.gemini/accounts/"
