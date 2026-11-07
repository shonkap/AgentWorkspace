"""Summaries of parsed log records."""


def summarize(records):
    by_status = {}
    for r in records:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"total": len(records), "by_status": by_status}
