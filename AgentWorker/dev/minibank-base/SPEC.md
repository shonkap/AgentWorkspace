# minibank spec

Amounts are integer cents internally. Money strings are dollars with up to 2 decimals ("10", "10.5", "0.07").

## ledger.py
- `parse_amount` (move it to ledger.py, keep cli importing it): exact conversion without float error
  ("0.07" -> 7, "19.99" -> 1999, "10" -> 1000, "10.5" -> 1050). Anything else (negative, 3 decimals, text,
  zero) raises `ValueError`.
- `Account.deposit/withdraw` reject amounts <= 0 with `ValueError`.
- `withdraw` more than the balance raises `InsufficientFunds` and changes nothing.
- `Bank.open` of an existing owner raises `ValueError`; `Bank.get` of an unknown owner raises `KeyError`.
- `Bank.transfer(src, dst, amount)` is atomic: on any error neither account changes. src == dst raises ValueError.
  History entries: src gets ("transfer_out", amount, dst), dst gets ("transfer_in", amount, src).

## cli.py
Commands, one per line; blank lines and lines starting with `#` are ignored:
`open NAME`, `deposit NAME AMOUNT`, `withdraw NAME AMOUNT`, `transfer FROM TO AMOUNT`, `balance NAME`, `report`.
- `balance NAME` prints `NAME $D.CC` (e.g. `alice $10.07`).
- A failing command prints `error line N: MESSAGE` (N is the 1-based line number in the script) and the script
  continues. MESSAGE is `insufficient funds`, `unknown account NAME`, `bad amount AMOUNT`, `account exists NAME`,
  `same account`, or `unknown command CMD`.
- `report` prints one line per account sorted by owner: `NAME $D.CC (N transactions)`, then `TOTAL $D.CC`.
- Exit code 0 even when commands fail.

## report.py
`format_money(cents) -> "$D.CC"` (e.g. 5 -> "$0.05", 123456 -> "$1234.56"). cli uses it.
