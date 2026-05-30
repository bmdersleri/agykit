#!/usr/bin/env bash
# Run all agykit tests. Exit non-zero if any suite fails.
set -uo pipefail
THIS_DIR=$(cd "$(dirname "$0")" && pwd)

rc=0
for t in "$THIS_DIR"/test_*.sh; do
    echo "══════ $(basename "$t") ══════"
    bash "$t" || rc=1
    echo
done
[ "$rc" -eq 0 ] && echo "ALL SUITES PASSED" || echo "SOME SUITES FAILED"
exit "$rc"
