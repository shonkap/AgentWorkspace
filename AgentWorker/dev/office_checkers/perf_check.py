#!/usr/bin/env python3
"""Performance check for the office game: 600 headless frames must render in under the limit.
    python3 perf_check.py [limit_seconds]   (default 2.5)"""
import os
import subprocess
import sys
import time

limit = float(sys.argv[1]) if len(sys.argv) > 1 else 2.5
env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
here = os.path.dirname(os.path.abspath(__file__))
t0 = time.monotonic()
r = subprocess.run([sys.executable, "tamagotchi/main.py", "--frames", "600"], cwd=here, env=env, capture_output=True, text=True)
secs = time.monotonic() - t0
if r.returncode != 0:
    print(f"FAIL  the game runs 600 frames  ->  exit code {r.returncode}: {r.stderr.strip().splitlines()[-1:]}")
    sys.exit(1)
ok = secs <= limit
print(("PASS" if ok else "FAIL") + f"  600 frames render in at most {limit:.1f} s  ->  took {secs:.2f} s ({600 / secs:.0f} fps)")
sys.exit(0 if ok else 1)
