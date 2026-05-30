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

echo "Left intact: ~/.gemini/accounts/ (snapshots), .agykit.conf (project config)."
echo "To purge account snapshots: rm -rf ~/.gemini/accounts/"
