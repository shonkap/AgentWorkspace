#!/usr/bin/env python3
"""Compact timeline of one worker run from its JSONL event log.
usage: dev/show_run.py [log.jsonl | task-stem]   (default: newest log in ~/ai-agent-workspace/logs)"""
import glob
import json
import os
import sys

LOGS = os.path.expanduser("~/ai-agent-workspace/logs")
arg = sys.argv[1] if len(sys.argv) > 1 else None
if arg and os.path.exists(arg):
    path = arg
else:
    cands = [p for p in glob.glob(os.path.join(LOGS, f"{arg or ''}*.jsonl")) if not p.endswith("worker.jsonl")]
    path = max(cands, key=os.path.getmtime)
print(path)
turn_secs = 0.0
for line in open(path):
    e = json.loads(line)
    ev = e["event"]
    if ev == "tool":
        res = e.get("result", "").replace("\n", " ")
        ex = f" exit={e['exit_code']}" if e.get("exit_code") is not None else ""
        print(f"{e['turn']:>3} {e['label'][:60]:<60}{ex} | {res[:90]}")
    elif ev == "model_turn":
        turn_secs += e["seconds"]
        print(f"    model t{e['turn']} {e['seconds']}s think={e['think']}({e['think_chars']}) gen={e['gen_tokens']} prompt={e['prompt_tokens']}")
    elif ev == "task_end":
        print(f"  == END success={e['success']} reason={e['reason'][:150]} turns={e.get('turns')} model_s={turn_secs:.0f}")
    else:
        rest = {k: str(v)[:90] for k, v in e.items() if k not in ("ts", "event")}
        print(f"  EV {ev} {rest}")
