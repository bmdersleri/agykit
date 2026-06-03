import datetime
import os
import sqlite3

from ._common import _apply_range

_DB_PATH = "~/.omniroute/storage.sqlite"


def _open_db(db_path: str | None = None) -> sqlite3.Connection | None:
    path = os.path.expanduser(db_path or _DB_PATH)
    if not os.path.isfile(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def omniroute_series(range_key: str = "all", *, db_path: str | None = None) -> dict:
    """Return daily token-usage series from omniroute's usage_history table.

    Returns:
        {
            "labels": ["2026-05-29", ...],
            "input_tokens": [...],
            "output_tokens": [...],
            "cache_tokens": [...],
            "requests": [...],
            "tokens_by_provider": {"claude": [...], "codex": [...], ...},
            "warning": str | None,
        }
    """
    con = _open_db(db_path)
    if con is None:
        db = os.path.expanduser(db_path or _DB_PATH)
        return {
            "labels": [],
            "input_tokens": [],
            "output_tokens": [],
            "cache_tokens": [],
            "requests": [],
            "tokens_by_provider": {},
            "warning": f"omniroute DB not found: {db}",
        }

    try:
        rows = con.execute(
            """
            SELECT substr(timestamp, 1, 10) AS day,
                   provider,
                   COUNT(*)                AS requests,
                   SUM(tokens_input)       AS input_tok,
                   SUM(tokens_output)      AS output_tok,
                   SUM(tokens_cache_read)  AS cache_tok
            FROM usage_history
            GROUP BY day, provider
            ORDER BY day
            """
        ).fetchall()
    except Exception as e:
        con.close()
        return {
            "labels": [],
            "input_tokens": [],
            "output_tokens": [],
            "cache_tokens": [],
            "requests": [],
            "tokens_by_provider": {},
            "warning": f"DB query failed: {e}",
        }
    finally:
        con.close()

    # Build per-day aggregates
    day_totals: dict[str, dict] = {}
    day_by_provider: dict[str, dict[str, int]] = {}
    all_providers: set[str] = set()

    for row in rows:
        day = row["day"]
        provider = row["provider"] or "unknown"
        inp = int(row["input_tok"] or 0)
        out = int(row["output_tok"] or 0)
        cch = int(row["cache_tok"] or 0)
        req = int(row["requests"] or 0)

        if day not in day_totals:
            day_totals[day] = {"input": 0, "output": 0, "cache": 0, "requests": 0}
        day_totals[day]["input"] += inp
        day_totals[day]["output"] += out
        day_totals[day]["cache"] += cch
        day_totals[day]["requests"] += req

        if day not in day_by_provider:
            day_by_provider[day] = {}
        day_by_provider[day][provider] = (
            day_by_provider[day].get(provider, 0) + inp + out
        )
        all_providers.add(provider)

    all_days = sorted(day_totals.keys())

    # Apply range filter
    filtered = _apply_range(all_days, range_key)
    labels = filtered

    input_tokens = [day_totals[d]["input"] for d in labels]
    output_tokens = [day_totals[d]["output"] for d in labels]
    cache_tokens = [day_totals[d]["cache"] for d in labels]
    requests = [day_totals[d]["requests"] for d in labels]

    # Per-provider totals (input + output) per day
    tokens_by_provider: dict[str, list[int]] = {}
    for provider in sorted(all_providers):
        tokens_by_provider[provider] = [
            day_by_provider.get(d, {}).get(provider, 0) for d in labels
        ]

    return {
        "labels": labels,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_tokens": cache_tokens,
        "requests": requests,
        "tokens_by_provider": tokens_by_provider,
        "warning": None,
    }


def omniroute_summary(*, db_path: str | None = None) -> dict:
    """Return overall token stats from omniroute.

    Returns:
        {
            "total_requests": int,
            "total_input_tokens": int,
            "total_output_tokens": int,
            "total_cache_tokens": int,
            "by_provider": {"claude": {"requests": N, "tokens": N}, ...},
            "by_model": {"claude-sonnet-4-6": {...}, ...},
            "warning": str | None,
        }
    """
    con = _open_db(db_path)
    if con is None:
        db = os.path.expanduser(db_path or _DB_PATH)
        return {
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_tokens": 0,
            "by_provider": {},
            "by_model": {},
            "warning": f"omniroute DB not found: {db}",
        }

    try:
        # By provider
        prov_rows = con.execute(
            """
            SELECT provider,
                   COUNT(*)               AS requests,
                   SUM(tokens_input)      AS input_tok,
                   SUM(tokens_output)     AS output_tok,
                   SUM(tokens_cache_read) AS cache_tok
            FROM usage_history
            GROUP BY provider
            ORDER BY input_tok DESC
            """
        ).fetchall()

        # By model (top 20)
        model_rows = con.execute(
            """
            SELECT model, provider,
                   COUNT(*)               AS requests,
                   SUM(tokens_input)      AS input_tok,
                   SUM(tokens_output)     AS output_tok
            FROM usage_history
            WHERE model IS NOT NULL AND model != ''
            GROUP BY model, provider
            ORDER BY input_tok DESC
            LIMIT 20
            """
        ).fetchall()
    except Exception as e:
        con.close()
        return {
            "total_requests": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_tokens": 0,
            "by_provider": {},
            "by_model": {},
            "warning": f"DB query failed: {e}",
        }
    finally:
        con.close()

    by_provider: dict[str, dict] = {}
    total_req = total_in = total_out = total_cache = 0

    for r in prov_rows:
        p = r["provider"] or "unknown"
        inp = int(r["input_tok"] or 0)
        out = int(r["output_tok"] or 0)
        cch = int(r["cache_tok"] or 0)
        req = int(r["requests"] or 0)
        by_provider[p] = {
            "requests": req,
            "input_tokens": inp,
            "output_tokens": out,
            "cache_tokens": cch,
        }
        total_req += req
        total_in += inp
        total_out += out
        total_cache += cch

    by_model: dict[str, dict] = {}
    for r in model_rows:
        key = (
            f"{r['provider']}/{r['model']}"
            if r["provider"]
            else (r["model"] or "unknown")
        )
        by_model[key] = {
            "requests": int(r["requests"] or 0),
            "input_tokens": int(r["input_tok"] or 0),
            "output_tokens": int(r["output_tok"] or 0),
        }

    return {
        "total_requests": total_req,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cache_tokens": total_cache,
        "by_provider": by_provider,
        "by_model": by_model,
        "warning": None,
    }
