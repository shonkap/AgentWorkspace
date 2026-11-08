#!/usr/bin/env python3
"""Layout check for the office menus: everything fits inside its panel, nothing overlaps, nothing is hidden by the HUD.

For each menu opened with --open KIND, --dump-state must contain "menu_layout" in WINDOW pixels (960x540):
    {"panel": [x, y, w, h], "title": [x, y, w, h], "lines": [[x, y, w, h], ...], "items": [[x, y, w, h], ...],
     "hint": [x, y, w, h]}
with the rectangle of every piece of text as actually drawn (font.size() of the rendered string). The check also
compares the screenshot with and without the menu: nothing may be drawn outside the reported panel.
    python3 ui_check.py
"""
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
HUD_TOP = 460                        # the bottom HUD bar starts here (window pixels)
CASES = {"desktop": [], "vending": [], "client": ["--start-minute", "600"], "fax": ["--start-minute", "660"]}
ok_all = True


def check(name, ok, detail=""):
    global ok_all
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "  ->  " + detail))
    ok_all &= bool(ok)


def run(args):
    tmp = tempfile.mkdtemp()
    shot, state = os.path.join(tmp, "s.png"), os.path.join(tmp, "s.json")
    r = subprocess.run([sys.executable, "tamagotchi/main.py", *args, "--frames", "10", "--screenshot", shot,
                        "--dump-state", state], cwd=HERE, env=ENV, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None, None, (r.stderr.strip().splitlines() or ["?"])[-1]
    return Image.open(shot).convert("RGB"), json.load(open(state)), ""


def inside(a, b, m=0):
    return a[0] >= b[0] - m and a[1] >= b[1] - m and a[0] + a[2] <= b[0] + b[2] + m and a[1] + a[3] <= b[1] + b[3] + m


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def valid(r):
    return isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r) and r[2] > 0 and r[3] > 0


for kind, extra in CASES.items():
    base_img, _, err = run(extra)
    img, st, err2 = run(extra + ["--open", kind])
    if img is None or base_img is None:
        check(f"{kind}: the game runs with --open {kind}", False, err or err2)
        continue
    lay = st.get("menu_layout")
    if not isinstance(lay, dict):
        check(f"{kind}: --dump-state reports menu_layout", False, 'add "menu_layout" (see the docstring of ui_check.py)')
        continue
    panel = lay.get("panel")
    texts = [("title", lay.get("title"))] + [(f"line {i + 1}", r) for i, r in enumerate(lay.get("lines") or [])] \
        + [(f"item {i + 1}", r) for i, r in enumerate(lay.get("items") or [])] + [("hint", lay.get("hint"))]
    bad = [n for n, r in [("panel", panel)] + texts if not valid(r)]
    if bad:
        check(f"{kind}: menu_layout rectangles are [x, y, w, h] with w, h > 0", False, f"malformed: {bad}")
        continue
    n_items = len((st.get("menu") or {}).get("items") or [])
    check(f"{kind}: menu_layout has one rectangle per menu item", len(lay.get("items") or []) == n_items,
          f"{len(lay.get('items') or [])} item rects for {n_items} items")
    check(f"{kind}: the panel is inside the window and above the HUD bar (y < {HUD_TOP})",
          panel[0] >= 0 and panel[1] >= 0 and panel[0] + panel[2] <= 960 and panel[1] + panel[3] <= HUD_TOP,
          f"panel {panel}")
    out = [n for n, r in texts if not inside(r, panel)]
    check(f"{kind}: every text fits inside the panel", not out, f"outside the panel {panel}: " +
          "; ".join(f"{n} {r}" for n, r in texts if n in out)[:400] + ". Make the panel bigger, the font smaller, or wrap/shorten")
    clashes = [(a, b) for i, (a, ra) in enumerate(texts) for (b, rb) in texts[i + 1:] if overlap(ra, rb)]
    check(f"{kind}: no two texts overlap", not clashes, "overlapping: " + "; ".join(f"{a} & {b}" for a, b in clashes[:5]))
    diff = ImageChops.difference(img, base_img).getbbox()
    check(f"{kind}: nothing is drawn outside the reported panel", diff is None or inside(list(diff[:2]) + [diff[2] - diff[0], diff[3] - diff[1]], panel, 2),
          f"the menu changed pixels in box {diff}, but the panel is {panel}")
    img.save(os.path.join(HERE, f"ui_{kind}.png"))

print()
print("UI CHECK PASSED" if ok_all else "UI CHECK FAILED (screenshots saved as ui_<kind>.png)")
sys.exit(0 if ok_all else 1)
