#!/usr/bin/env python3
"""Acceptance checker for minibank. Prints PASS/FAIL lines; exits 1 if anything fails."""
import importlib
import os
import subprocess
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, fn):
    try:
        msg = fn()
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        where = next((f"{os.path.relpath(f.filename)}:{f.lineno}" for f in reversed(tb) if "minibank" in f.filename), "")
        msg = f"{type(e).__name__}: {e}" + (f" [at {where} in {tb[-1].name}]" if where else "")
    results.append((name, msg))
    print(f"PASS  {name}" if msg is None else f"FAIL  {name}  ->  {msg}")


def raises(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    except Exception as e:
        return f"raised {type(e).__name__} instead of {exc.__name__}"
    return f"did not raise {exc.__name__}"


def mod(name):
    return importlib.import_module(f"minibank.{name}")


print("== ledger ==")
for text, want in [("0.07", 7), ("19.99", 1999), ("10", 1000), ("10.5", 1050), ("0.29", 29), ("1234.56", 123456)]:
    def t(text=text, want=want):
        got = mod("ledger").parse_amount(text)
        return None if got == want and isinstance(got, int) else f"parse_amount({text!r}) = {got!r}, expected {want}"
    check(f"parse_amount({text!r}) == {want}", t)
for bad in ["-5", "1.234", "abc", "0", "", "1e3", "0.00"]:
    def t(bad=bad):
        r = raises(ValueError, mod("ledger").parse_amount, bad)
        return None if r is True else f"parse_amount({bad!r}) {r}"
    check(f"parse_amount({bad!r}) raises ValueError", t)


def t():
    L = mod("ledger"); a = L.Account("a")
    for amt in (0, -100):
        for fn in (a.deposit, a.withdraw):
            r = raises(ValueError, fn, amt)
            if r is not True:
                return f"{fn.__name__}({amt}) {r}"
check("deposit/withdraw reject amounts <= 0", t)


def t():
    L = mod("ledger"); a = L.Account("a"); a.deposit(500)
    r = raises(L.InsufficientFunds, a.withdraw, 501)
    if r is not True:
        return f"withdraw(501) with balance 500 {r}"
    return None if a.balance == 500 and len(a.history) == 1 else f"failed withdraw changed the account: balance {a.balance}, history {a.history}"
check("overdraft raises InsufficientFunds and changes nothing", t)


def t():
    L = mod("ledger"); b = L.Bank(); b.open("x")
    r1 = raises(ValueError, b.open, "x"); r2 = raises(KeyError, b.get, "nobody")
    return None if r1 is True and r2 is True else f"open twice: {r1}; get unknown: {r2}"
check("Bank.open twice -> ValueError, Bank.get unknown -> KeyError", t)


def t():
    L = mod("ledger"); b = L.Bank(); a = b.open("a"); c = b.open("c"); a.deposit(1000)
    b.transfer("a", "c", 300)
    if (a.balance, c.balance) != (700, 300):
        return f"balances after transfer {(a.balance, c.balance)}, expected (700, 300)"
    if a.history[-1] != ("transfer_out", 300, "c") or c.history[-1] != ("transfer_in", 300, "a"):
        return f"history entries {a.history[-1]!r} / {c.history[-1]!r}"
check("transfer moves money and records transfer_out/transfer_in", t)


def t():
    L = mod("ledger"); b = L.Bank(); a = b.open("a"); a.deposit(1000)
    r = raises(KeyError, b.transfer, "a", "ghost", 300)
    if r is not True:
        return f"transfer to unknown account {r}"
    if a.balance != 1000 or len(a.history) != 1:
        return f"failed transfer to an unknown account still changed the source: balance {a.balance}, history {a.history}"
    b.open("d")
    r = raises(L.InsufficientFunds, b.transfer, "a", "d", 5000)
    return None if r is True and b.get("d").balance == 0 else f"overdraft transfer: {r}, d balance {b.get('d').balance}"
check("transfer is atomic on errors", t)


def t():
    L = mod("ledger"); b = L.Bank(); a = b.open("a"); a.deposit(100)
    r = raises(ValueError, b.transfer, "a", "a", 10)
    return None if r is True else f"transfer to self {r}"
check("transfer to the same account raises ValueError", t)

print("== report ==")
for cents, want in [(5, "$0.05"), (123456, "$1234.56"), (0, "$0.00"), (100, "$1.00"), (99, "$0.99")]:
    def t(cents=cents, want=want):
        got = mod("report").format_money(cents)
        return None if got == want else f"format_money({cents}) = {got!r}, expected {want!r}"
    check(f"format_money({cents}) == {want!r}", t)

print("== cli ==")
SCRIPT = """# demo
open alice
open bob
deposit alice 10.07
deposit bob 0.29
withdraw alice 20
transfer alice bob 5
balance alice
balance bob

transfer alice carol 1
open alice
deposit bob -3
deposit bob 1.234
fly bob
transfer bob bob 1
report
"""
EXPECTED = """error line 6: insufficient funds
alice $5.07
bob $5.29
error line 11: unknown account carol
error line 12: account exists alice
error line 13: bad amount -3
error line 14: bad amount 1.234
error line 15: unknown command fly
error line 16: same account
alice $5.07 (2 transactions)
bob $5.29 (2 transactions)
TOTAL $10.36""".splitlines()


def run_cli(script):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(script)
    try:
        return subprocess.run([sys.executable, "-m", "minibank.cli", f.name], capture_output=True, text=True, timeout=30,
                              cwd=os.path.dirname(os.path.abspath(__file__)))
    finally:
        os.unlink(f.name)


proc = run_cli(SCRIPT)
lines = proc.stdout.strip().splitlines()


def t():
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()
        return f"exit code {proc.returncode}; stderr ends with: {err[-1] if err else '(empty)'}"
check("cli runs the demo script with exit code 0", t)
for i, want in enumerate(EXPECTED):
    def t(i=i, want=want):
        got = lines[i] if i < len(lines) else "(missing)"
        return None if got == want else f"output line {i + 1} is {got!r}, expected {want!r}"
    check(f"cli output line {i + 1}: {want}", t)


def t():
    return None if len(lines) == len(EXPECTED) else f"{len(lines)} output lines, expected {len(EXPECTED)}"
check("cli prints exactly the expected number of lines", t)

failed = [n for n, m in results if m is not None]
print()
print("ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED")
sys.exit(1 if failed else 0)
