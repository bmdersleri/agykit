import re
import subprocess

_ROW_RE = re.compile(
    r"^\s*(\d+)\.\s+(.+?)\s{2,}(\d+)\s+([\d.]+[KMkm]?)\s+([\d.]+)%"
)


def _parse_suffix(s: str) -> int:
    s = s.strip()
    if s.endswith("M") or s.endswith("m"):
        return int(float(s[:-1]) * 1_000_000)
    if s.endswith("K") or s.endswith("k"):
        return int(float(s[:-1]) * 1_000)
    return int(float(s))


def rtk_stats() -> dict:
    _EMPTY = {
        "total_commands": 0,
        "tokens_saved": 0,
        "efficiency_pct": 0.0,
        "top_commands": [],
        "warning": None,
    }

    try:
        proc = subprocess.run(
            ["rtk", "gain"], capture_output=True, text=True, timeout=5
        )
        out = proc.stdout
    except Exception as e:
        result = {**_EMPTY, "warning": str(e)}
        return result

    total_commands = 0
    tokens_saved = 0
    efficiency_pct = 0.0
    top_commands = []

    for line in out.splitlines():
        m = re.search(r"Total commands:\s+([\d,]+)", line)
        if m:
            total_commands = int(m.group(1).replace(",", ""))

        m = re.search(r"Tokens saved:\s+([\d.]+[KMkm]?)\s+\(([\d.]+)%\)", line)
        if m:
            tokens_saved = _parse_suffix(m.group(1))
            efficiency_pct = float(m.group(2))

        m = _ROW_RE.match(line)
        if m:
            top_commands.append({
                "rank": int(m.group(1)),
                "cmd": m.group(2).strip(),
                "count": int(m.group(3)),
                "saved": _parse_suffix(m.group(4)),
                "avg_pct": float(m.group(5)),
            })

    return {
        "total_commands": total_commands,
        "tokens_saved": tokens_saved,
        "efficiency_pct": efficiency_pct,
        "top_commands": top_commands,
        "warning": None,
    }
