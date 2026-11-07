# Session notes (2026-11-07): worker.py improvements

Branch: `worker-improvements`. See HANDOFF.md for the background.

## What I found
- officeV10 had run 40 turns and was then stopped. It only read files and never changed one: each turn was a single
  `read_file` of about 20 tokens, with thinking off. History trimming meant it kept re-reading the same files
  (check_office2.py four times).
- The game checker prints about 150 PASS lines. Head+tail truncation to 4000 chars hid most FAIL lines from the model.
- The prompt said "Reply with tool tags only, no explanations". That, plus thinking being off on most turns, meant the
  model did no planning.
- "Never edit the judges" was only a request in the prompt. Nothing enforced it.
- `check_office2.py` takes **about 6m40s** per run (the game runs at about 90 fps headless, and every scenario runs
  twice). The harness's periodic status check re-ran it every 10 turns, even right after the model had just run it.
- dev/agent_worker_e2e_test.py, dev/checker_selftest/ and summarize_runs.py from HANDOFF.md are not on this machine.

## Harness changes (worker.py)
| Change | Why |
|---|---|
| `compress_output`: runs of PASS / `... ok` lines collapse into a counter | every FAIL line stays visible |
| `PROTECT: file` task header: edits are refused; a file changed through the shell is restored after the turn | judges cannot be edited |
| Read dedup: re-reading an unchanged file while its earlier read is still in history returns "UNCHANGED, see turn N" | stops re-read loops |
| Read lock: after 8 read-only turns, read_file/list_dir are refused until the model **edits** a file (running a command does not unlock) | the model had beaten the first version by running a trivial command |
| Verify-result cache, keyed by a file-change counter | harness status checks reuse the model's own identical run (saves about 7 min per status) |
| Periodic status is skipped when nothing has changed since the last one | |
| Auto-verify: after an edit-only turn the harness runs the checks itself, but only if they are cheap (measured at 90 s or less) | saves a turn per edit on small projects |
| Initial status: for an existing project, the checks run before turn 1 and the failures are pinned | the model starts from the facts instead of reading a 1200-line checker |
| Code map in the task prompt: files, line counts, `def`/`class` lines | targeted reads |
| Prompt: asks for LEARNED/PLAN lines, then tags; edit and test in the same reply; removed "tags only, no explanations" | |
| Images are auto-attached only from command output (a file name in a directory listing had triggered it) | |
| Removed game-specific hints (`tamagotchi/main.py`) from the generic nudges | |
| `max_output_chars` raised from 4000 to 8000 | output is now mostly failures |

## Tests
- `./venv/bin/python dev/test_worker.py`: 6 scenario tests with a fake sandbox and a scripted fake model.
- `dev/minibank-base/`: a small buggy ledger project with a protected checker (`check_bank.py`, checked against a
  reference solution). Run it with `dev/run_test.sh dev/minibank-base dev/minibank_task.txt minibank --max-iterations 40`.
- `dev/show_run.py [task-stem]`: a compact timeline of a run from its JSONL log.

## Runs
- minibank_115039: PASSED in 14 turns, 88 s of model time.
- officeV11: stopped by me at turn 14 (it was still on the old read-lock logic and only read the checker). Requeued as V12.
