import os
import json
from collections import deque

_OPS_LOG_DEFAULT = "~/.gemini/agykit-ops.log"


def ops_log(*, log_path: str | None = None, limit: int = 50) -> dict:
    """Return last N entries from the agykit operations log (~/.gemini/agykit-ops.log).

    Each entry: {ts, cmd, status, account, model, prompt}
    """
    path = os.path.expanduser(log_path or _OPS_LOG_DEFAULT)
    if not os.path.isfile(path):
        return {"entries": [], "total": 0, "warning": f"Ops log not found: {path}"}
    total = 0
    skipped = 0
    window: deque = deque(maxlen=limit)
    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    window.append(json.loads(line))
                    total += 1
                except json.JSONDecodeError:
                    skipped += 1
    except Exception as e:
        return {"entries": [], "total": 0, "warning": str(e)}
    result = {"entries": list(window), "total": total}
    if skipped:
        result["warning"] = f"Skipped {skipped} malformed lines"
    return result
