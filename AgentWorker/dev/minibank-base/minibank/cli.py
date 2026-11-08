"""Run a script of bank commands: python3 -m minibank.cli script.txt"""
import sys

from minibank.ledger import Bank


def parse_amount(text):
    return int(float(text) * 100)


def run(lines):
    bank = Bank()
    out = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        cmd = parts[0]
        if cmd == "open":
            bank.open(parts[1])
        elif cmd == "deposit":
            bank.get(parts[1]).deposit(parse_amount(parts[2]))
        elif cmd == "withdraw":
            bank.get(parts[1]).withdraw(parse_amount(parts[2]))
        elif cmd == "balance":
            out.append(f"{parts[1]} {bank.get(parts[1]).balance}")
    return out


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        print("\n".join(run(f.read().splitlines())))
