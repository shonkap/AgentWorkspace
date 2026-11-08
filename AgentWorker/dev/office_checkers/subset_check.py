#!/usr/bin/env python3
"""Acceptance check for a focused task: the named checks of check_office2.py must pass, and nothing that passed before
may break.
    python3 subset_check.py BASELINE_FILE "substring" ["substring" ...]
BASELINE_FILE lists (one per line) the check names that were failing when the task started.
A check is TARGETED when its name contains one of the substrings (the [live] variant counts too)."""
import re
import subprocess
import sys

HERE = __file__.rsplit("/", 1)[0] or "."
baseline_file, targets = sys.argv[1], sys.argv[2:]
base = {l.strip() for l in open(f"{HERE}/{baseline_file}") if l.strip()}
r = subprocess.run([sys.executable, "check_office2.py"], cwd=HERE, capture_output=True, text=True)
fails = {}
for line in r.stdout.splitlines():
    m = re.match(r"^FAIL  (.*?)  ->  (.*)$", line)
    if m:
        fails[m.group(1)] = m.group(2)

ok = True
for name, why in fails.items():
    if any(t in name for t in targets):
        print(f"FAIL  {name}  ->  {why}")
        ok = False
for name, why in fails.items():
    if name not in base and not any(t in name for t in targets):
        print(f"FAIL  [REGRESSION: this passed before your change] {name}  ->  {why}")
        ok = False
fixed = sorted(n for n in base if n not in fails)
for name in fixed:
    print(f"PASS  {name}")
other = sorted(n for n in fails if n in base and not any(t in n for t in targets))
if other:
    print(f"INFO  {len(other)} other check(s) still fail, as before; they are NOT part of this task: {other[:6]}")
print()
print("SUBSET CHECK PASSED" if ok else "SUBSET CHECK FAILED")
sys.exit(0 if ok else 1)
