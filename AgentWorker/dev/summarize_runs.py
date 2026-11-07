#!/usr/bin/env python3
"""One line per worker run, from ~/ai-agent-workspace/logs/*.jsonl: outcome, turns, model time, edits vs reads, checks.
usage: dev/summarize_runs.py [name-filter]"""
import glob
import json
import os
import sys

LOGS = os.path.expanduser("~/ai-agent-workspace/logs")
filt = sys.argv[1] if len(sys.argv) > 1 else ""
rows = []
for path in sorted(glob.glob(os.path.join(LOGS, "*.jsonl")), key=os.path.getmtime):
    name = os.path.basename(path)[:-6]
    if name == "worker" or filt not in name:
        continue
    r = {"run": name, "end": "-", "turns": 0, "model_s": 0.0, "edits": 0, "reads": 0, "cmds": 0, "think_cut": 0,
         "verify_s": 0.0, "locks": 0, "quick": 0, "start": ""}
    for line in open(path):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ev = e.get("event")
        if ev == "task_start":
            r["start"] = e["ts"][5:16]
            r["think"] = e.get("think_mode", "")
        elif ev == "model_turn":
            r["turns"] = max(r["turns"], e.get("turn", 0))
            r["model_s"] += e.get("seconds", 0)
        elif ev == "tool":
            k = e.get("kind")
            r["edits" if k in ("write_file", "replace_in_file") else "reads" if k in ("read_file", "list_dir") else "cmds"] += 1
        elif ev == "thinking_budget_exhausted":
            r["think_cut"] += 1
        elif ev == "verify" and not e.get("cached"):
            r["verify_s"] += float(e.get("seconds", 0) or 0)
        elif ev == "readonly_nudge":
            r["locks"] += 1
        elif ev == "quick_check":
            r["quick"] += 1
        elif ev == "task_end":
            r["end"] = "PASS" if e.get("success") else "fail"
    rows.append(r)

cols = ["run", "start", "end", "turns", "model_s", "verify_s", "edits", "reads", "cmds", "quick", "think_cut", "locks"]
print("  ".join(f"{c:>9}" if c != "run" else f"{c:<24}" for c in cols))
for r in rows:
    print("  ".join(f"{r[c]:<24}" if c == "run" else f"{r[c]:>9.0f}" if isinstance(r[c], float) else f"{r[c]:>9}" for c in cols))
