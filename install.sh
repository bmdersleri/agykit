#!/usr/bin/env bash
# agykit installer — symlinks agykit into PATH, checks deps, scaffolds config.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGYKIT_BIN="$SRC_DIR/agykit"
TARGET_DIR="${AGYKIT_PREFIX:-$HOME/.local/bin}"
TARGET="$TARGET_DIR/agykit"

echo "═══ agykit installer ═══"

# ── Dependency checks ────────────────────────────────────────────────────────
miss=0
check() { command -v "$1" >/dev/null 2>&1 && echo "  ✓ $1" || { echo "  ✗ $1 MISSING — $2"; miss=1; }; }
echo "Dependencies:"
check agy      "install Antigravity CLI: https://antigravity.google/cli"
check python3  "install Python 3"
check git      "install git"
check jq       "install jq (apt install jq / brew install jq)"
# python keyring module
if python3 -c "import keyring" 2>/dev/null; then echo "  ✓ python keyring"; else
    echo "  ✗ python keyring MISSING — pip install keyring"; miss=1; fi
[ "$miss" -eq 1 ] && { echo "Resolve missing deps above, then re-run."; exit 1; }

# ── Symlink ──────────────────────────────────────────────────────────────────
mkdir -p "$TARGET_DIR"
ln -sf "$AGYKIT_BIN" "$TARGET"
chmod +x "$AGYKIT_BIN"
echo "Installed: $TARGET -> $AGYKIT_BIN"

# ── PATH check ───────────────────────────────────────────────────────────────
case ":$PATH:" in
    *":$TARGET_DIR:"*) ;;
    *) echo "  ⚠ $TARGET_DIR not in PATH — add to your shell rc:"
       echo "      export PATH=\"$TARGET_DIR:\$PATH\"" ;;
esac

# ── Config scaffold ──────────────────────────────────────────────────────────
if [ ! -f ".agykit.conf" ] && [ -t 0 ]; then
    echo "No .agykit.conf in CWD. Create one? (copies example) [y/N]"
    read -r ans || ans="n"
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        cp "$SRC_DIR/agykit.conf.example" ".agykit.conf"
        echo "  Created .agykit.conf — edit AGYKIT_VERIFY for your project."
    fi
elif [ ! -f ".agykit.conf" ]; then
    echo "Tip: copy $SRC_DIR/agykit.conf.example to your project root as .agykit.conf"
fi

echo

# ── Post-install: agy OAuth check ────────────────────────────────────────────
echo "Post-install check:"
if python3 -c "
import keyring, sys
v = keyring.get_password('gemini', 'antigravity')
sys.exit(0 if v else 1)
" 2>/dev/null; then
    echo "  ✓ agy OAuth token found"
    "$TARGET" account-save 2>/dev/null \
        && echo "  ✓ account snapshot saved" \
        || echo "  ⚠ account-save failed — run manually: agykit account-save"
else
    echo "  ⚠ No agy OAuth token found"
    echo
    echo "  Next steps:"
    echo "    1. Run:  agy                   (complete Google OAuth login)"
    echo "    2. Run:  agykit account-save   (snapshot the login for rotation)"
    echo "    3. Run:  agykit doctor         (verify everything is set up)"
    echo
    echo "  Then in each project directory:"
    echo "    agykit init                    (create .agykit.conf interactively)"
fi
