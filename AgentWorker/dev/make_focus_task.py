#!/usr/bin/env python3
"""Write a focused game task: fix the named checks of check_office2.py without breaking anything else.
usage: dev/make_focus_task.py NAME BASELINE_FILE "description" "substring" ["substring" ...]   -> prints the task text"""
import shlex
import sys

name, baseline, desc, targets = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
tq = " ".join(shlex.quote(t) for t in targets)
print(f"""WORKDIR: office-game
REQUIRE: subset_check.py
REQUIRE: {baseline}
PROTECT: subset_check.py
PROTECT: {baseline}
PROTECT: check_office2.py
PROTECT: quick_check.py
PROTECT: perf_check.py
PROTECT: refactor_check.py
PROTECT: economy_ref.py
PROTECT: test_economy_ref.py
QUICKCHECK: python3 tamagotchi/main.py --frames 20 && python3 tamagotchi/main.py --script right:10,e:1,esc:1,down:5 --frames 40 && echo "PASS  smoke test"

FOCUSED TASK ({name}) for the office game in tamagotchi/ (only that folder is the live game; modules: main.py setup and
loop, input_router.py keys and routing, game_engine.py game state/update/state dump, render.py drawing, hud.py HUD,
world.py layout and collisions, economy.py rules engine - never change economy.py).

Make exactly these failing checks of check_office2.py pass (each also runs in a [live] variant), without breaking any
check that passes now:
{chr(10).join('  - ' + t for t in targets)}

{desc}

Work in small steps: one change, then run `python3 subset_check.py {baseline} {tq}` (about 75 s; it lists the
targeted failures and any REGRESSION). The original code is in git if you need to compare (`git log --oneline | head`).

VERIFY: python3 subset_check.py {baseline} {tq}
VERIFY: python3 -m unittest discover -s tamagotchi -p "test_*.py"
""")
