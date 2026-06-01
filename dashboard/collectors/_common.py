import datetime


def _apply_range(labels: list[str], range_key: str) -> list[str]:
    if not labels:
        return []
    if range_key == "all":
        return labels

    try:
        max_date = datetime.date.fromisoformat(max(labels))
    except ValueError:
        return labels

    if range_key == "7d":
        limit = max_date - datetime.timedelta(days=7)
    elif range_key == "30d":
        limit = max_date - datetime.timedelta(days=30)
    else:
        return labels

    return [d for d in labels if datetime.date.fromisoformat(d) > limit]
