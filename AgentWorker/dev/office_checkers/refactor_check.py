#!/usr/bin/env python3
"""Acceptance check for the main.py split: no new check_office2 failures, identical screenshots, small modules.
    python3 refactor_check.py          (runs the full check_office2.py, about 75 s)
    python3 refactor_check.py --sizes  (only the file-size part, instant)"""
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ok_all = True


def check(name, ok, detail=""):
    global ok_all
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "  ->  " + detail))
    ok_all &= ok


def sizes():
    main = os.path.join(HERE, "tamagotchi", "main.py")
    n = sum(1 for _ in open(main))
    check("tamagotchi/main.py has at most 250 lines", n <= 250, f"it has {n} lines; move more code into modules")
    for path in sorted(glob.glob(os.path.join(HERE, "tamagotchi", "*.py"))):
        base = os.path.basename(path)
        if base.startswith(("test_", "gen_")) or base in ("economy.py", "main.py"):
            continue
        n = sum(1 for _ in open(path))
        check(f"tamagotchi/{base} has at most 300 lines", n <= 300, f"it has {n} lines; split it")


def shots():
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    from PIL import Image, ImageChops
    for args, ref in ((["--frames", "30"], "ref_shot.png"), (["--script", "right:40,down:30", "--frames", "90"], "ref_shot_walk.png")):
        out = f"/tmp/refactor_{ref}"
        r = subprocess.run([sys.executable, "tamagotchi/main.py", *args, "--screenshot", out], cwd=HERE, env=env,
                           capture_output=True, text=True)
        if r.returncode != 0:
            check(f"the game runs with {' '.join(args)}", False, (r.stderr.strip().splitlines() or ["?"])[-1])
            continue
        got, want = Image.open(out).convert("RGB"), Image.open(os.path.join(HERE, ref)).convert("RGB")
        d = ImageChops.difference(got, want).getbbox()
        detail = ""
        if d is not None:
            diff = [(x, y) for y in range(d[1], d[3]) for x in range(d[0], d[2]) if got.getpixel((x, y)) != want.getpixel((x, y))]
            samples = "; ".join(f"window ({x},{y}) = view ({x // 2},{y // 2}): got {got.getpixel((x, y))} expected {want.getpixel((x, y))}"
                                for x, y in diff[:: max(1, len(diff) // 4)][:4])
            strip = Image.new("RGB", (d[2] - d[0], 3 * (d[3] - d[1]) + 8), (255, 0, 255))
            strip.paste(want.crop(d), (0, 0)); strip.paste(got.crop(d), (0, d[3] - d[1] + 4))
            mask = Image.new("RGB", (d[2] - d[0], d[3] - d[1]), (0, 0, 0))
            for x, y in diff:
                mask.putpixel((x - d[0], y - d[1]), (255, 255, 255))
            strip.paste(mask, (0, 2 * (d[3] - d[1]) + 8))
            strip.save(os.path.join(HERE, "refactor_diff.png"))
            detail = (f"{len(diff)} pixels differ inside box {d} (window pixels; the view is scaled 2x). Samples: {samples}. "
                      "Saved refactor_diff.png: top = expected, middle = yours, bottom = differing pixels in white. The code "
                      "before the split is in git: git show 9103edc:tamagotchi/main.py")
        check(f"screenshot with {' '.join(args)} is identical to {ref}", d is None, detail)


def regressions():
    base = {l.strip() for l in open(os.path.join(HERE, "refactor_baseline_fails.txt")) if l.strip()}
    r = subprocess.run([sys.executable, "check_office2.py"], cwd=HERE, capture_output=True, text=True)
    fails = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^FAIL  (.*?)  ->  (.*)$", line)
        if m:
            fails[m.group(1)] = m.group(2)
    new = {n: why for n, why in fails.items() if n not in base}
    check("check_office2.py: no check fails that passed before the split", not new,
          "; ".join(f"{n} -> {why[:200]}" for n, why in list(new.items())[:4]) + (f" ... and {len(new) - 4} more" if len(new) > 4 else ""))
    fixed = sorted(base - set(fails))
    if fixed:
        print(f"INFO  {len(fixed)} check(s) from the baseline now pass as well: {fixed[:5]}")


sizes()
if "--sizes" not in sys.argv:
    shots()
    regressions()
print()
print("REFACTOR CHECK PASSED" if ok_all else "REFACTOR CHECK FAILED")
sys.exit(0 if ok_all else 1)
