#!/usr/bin/env python3
"""Standalone agy model quota fetcher — caching wrapper around tmux capture.

Usage:
    python3 quota.py              # human-readable table (colored)
    python3 quota.py --json       # raw JSON
    python3 quota.py --refresh    # force re-fetch ignoring cache
    python3 quota.py --status     # one-line statusline summary

Cache: ~/.gemini/antigravity-cli/quota-cache.json (5min TTL)
"""
import argparse
import json
import os
import sys
import time

CACHE_FILE = os.path.expanduser("~/.gemini/antigravity-cli/quota-cache.json")
CACHE_TTL  = 300  # seconds

# ── ANSI helpers ─────────────────────────────────────────────────────────────
def col(c, s): return f"\033[{c}m{s}\033[0m"
def GREEN(s):
    return col(92, s)
def YELLOW(s):
    return col(93, s)
def RED(s):
    return col(91, s)
def CYAN(s):
    return col(96, s)
def DIM(s):
    return col(2,  s)
def BOLD(s):
    return col(1,  s)

# ── Cache ────────────────────────────────────────────────────────────────────
def load_cache():
    try:
        d = json.load(open(CACHE_FILE))
        age = time.time() - d.get("_ts", 0)
        if age < CACHE_TTL:
            return d, age
        return d, age  # return stale too, caller decides
    except Exception:
        return None, None

def save_cache(data):
    data["_ts"] = time.time()
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    json.dump(data, open(CACHE_FILE, "w"), ensure_ascii=False, indent=2)

# ── tmux fetch (imported from collectors) ────────────────────────────────────
def fetch_live():
    # Import collectors from the same directory
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dashboard.collectors import agy_model_quota_tmux
    return agy_model_quota_tmux()

# ── Rendering ────────────────────────────────────────────────────────────────
BAR_FULL = 20

def pct_color(pct):
    if pct is None:
        return DIM
    if pct >= 60:
        return GREEN
    if pct >= 25:
        return YELLOW
    return RED

def render_table(data, cache_age=None):
    account = data.get("account") or "—"
    plan    = data.get("plan")    or "—"
    ts      = data.get("captured_at") or "—"
    age_str = f"  {DIM(f'(cache {int(cache_age)}s ago)')}" if cache_age else ""

    print(BOLD("Model Quota") + f"  {CYAN(account)}  {DIM(plan)}  {DIM(ts)}{age_str}")
    print(DIM("─" * 72))

    for m in data.get("models", []):
        pct  = m.get("pct_shown") or m.get("pct_remaining") or 0
        name = m.get("display_name", "?")
        status = m.get("status", "available")
        refresh = m.get("refreshes_in") or ""

        filled = round(pct * BAR_FULL / 100)
        bar    = "█" * filled + "░" * (BAR_FULL - filled)
        cc     = pct_color(pct)
        pct_s  = cc(f"{pct:>3}%")
        bar_s  = cc(bar)

        refresh_s = DIM(f"  → {refresh}") if refresh else (
            DIM("  ✓") if status == "available" else "")

        print(f"  {name:<35} {bar_s} {pct_s}{refresh_s}")

    if data.get("warning"):
        print(YELLOW(f"\n⚠ {data['warning']}"))

def render_status(data, cache_age=None):
    """One-line summary for statusline use."""
    models = data.get("models", [])
    exhausted = [m for m in models if m.get("status") == "limited"]
    if not models:
        print("agy quota: no data")
        return
    if exhausted:
        names = ", ".join(m["display_name"].split("(")[0].strip() for m in exhausted[:2])
        refresh = exhausted[0].get("refreshes_in") or "?"
        print(f"⚠ {len(exhausted)} model(s) limited ({names}) → {refresh}")
    else:
        print(f"✓ {len(models)} models available")

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--json",    action="store_true", help="Output JSON")
    p.add_argument("--refresh", action="store_true", help="Force re-fetch")
    p.add_argument("--status",  action="store_true", help="One-line statusline")
    p.add_argument("--no-color",action="store_true", help="Disable ANSI colors")
    args = p.parse_args()

    if args.no_color:
        global GREEN, YELLOW, RED, CYAN, DIM, BOLD
        GREEN = YELLOW = RED = CYAN = DIM = BOLD = lambda s: s

    cache, cache_age = load_cache()
    fresh = cache_age is not None and cache_age < CACHE_TTL

    if args.refresh or not fresh:
        if not args.json and not args.status:
            if not fresh:
                print(DIM("Fetching quota from agy (~30s)…"), flush=True)
            else:
                print(DIM("Refreshing quota cache…"), flush=True)
        data = fetch_live()
        if data.get("models"):
            save_cache(data)
        age_to_show = None
    else:
        data = cache
        age_to_show = cache_age

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.status:
        render_status(data, age_to_show)
    else:
        render_table(data, age_to_show)

if __name__ == "__main__":
    main()
