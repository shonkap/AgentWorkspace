#!/usr/bin/env python3
"""Run only some sections of check_office2.py, for fast feedback while you work. The FULL check_office2.py stays the judge.

    python3 quick_check.py art       palette, characters, props, code and docs   (a few seconds)
    python3 quick_check.py script    gameplay in --script mode                   (about 3 minutes)
    python3 quick_check.py live      gameplay through the real live loop         (about 3 minutes)
    python3 quick_check.py art script ...   several sections in order
"""
import sys

import check_office2 as C

SECTIONS = ("art", "script", "live")


def main():
    wanted = sys.argv[1:] or ["art"]
    bad = [w for w in wanted if w not in SECTIONS]
    if bad:
        print(f"unknown section(s) {bad}; choose from {SECTIONS}")
        sys.exit(2)
    have_main = True
    if "art" in wanted:
        print("== palette ==");            C.check_palette()
        print("== characters ==");         C.check_characters()
        print("== props, tiles, ui, backgrounds =="); C.check_props_and_misc()
        print("== code and docs ==");      have_main = C.check_code()
    if "script" in wanted and have_main:
        print("== gameplay (--script mode) ==")
        C.LIVE_MODE = False
        C.check_gameplay()
    if "live" in wanted and have_main:
        print("== gameplay through the REAL live loop ==")
        C.LIVE_MODE = True
        C.check_gameplay()
        C.LIVE_MODE = False
    print()
    if C.failures:
        print(f"{len(C.failures)} CHECK(S) FAILED in the quick sections {wanted} (the full judge is check_office2.py)")
        sys.exit(1)
    print(f"QUICK SECTIONS {wanted} PASSED (now run the full python3 check_office2.py)")


if __name__ == "__main__":
    main()
