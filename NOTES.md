# Session notes (2026-11-07): worker.py improvements

Branch: `worker-improvements` (one commit per change). See HANDOFF.md for the background.

## What I found
- officeV10 had run 40 turns and was then stopped. It only read files and never changed one: each turn was a single
  `read_file` of about 20 tokens, with thinking off. History trimming meant it kept re-reading the same files.
- The game checker prints about 450 PASS lines. Head+tail truncation to 4000 chars hid most FAIL lines from the model.
- The prompt said "Reply with tool tags only, no explanations". With thinking off on most turns, the model did no planning.
- "Never edit the judges" was only a request in the prompt. Nothing enforced it.
- `check_office2.py` takes **about 6m40s** per run (the game runs at about 90 fps headless, and every scenario runs
  twice). The harness re-ran it for status checks even when nothing had changed.
- dev/agent_worker_e2e_test.py, dev/checker_selftest/ and summarize_runs.py from HANDOFF.md are not on this machine.
- Killing the worker leaves its commands running inside the container (docker exec does not stop them).

## Harness changes (worker.py), roughly in order of impact
| Change | Why |
|---|---|
| **FOCUS NOW** line in the pinned status: one named failing check to fix in the next reply | this is what finally got the model from reading to editing |
| Initial status: for an existing project, the checks run before turn 1 and the failures are pinned | the model starts from the facts |
| `compress_output`: runs of PASS / `... ok` lines collapse into a counter | every FAIL line stays visible |
| `QUICKCHECK: cmd` task header: fast checks the harness runs after every successful edit-only turn | feedback within seconds |
| Pinned status is pruned when a later partial run shows PASS for a listed check, and FOCUS moves to the next one | |
| The status refreshes whenever the model runs a verify command itself (that result is cached, so it is free) | |
| Verify cache keyed by a content fingerprint of the work dir (md5 of the files), and persisted in `logs/verify_cache_*.json` | no repeated 7-minute runs on unchanged files |
| Green auto-complete only when every check is cheap or cached | a 0.2 s asset script no longer launches the 7-minute checker |
| Auto-verify after an edit-only turn when the checks are cheap (90 s or less), or after 3 blind edit turns in a row | |
| `PROTECT: file` header: edits are refused; a file changed through the shell is restored. read_file shows at most 200 lines of each protected file | judges stay intact; the model stops studying the checker |
| Read tracking by line coverage: unchanged lines already in history return "UNCHANGED"; after 8 read-only turns, re-reads are locked until an **edit** (new files and new ranges stay readable) | stops re-read loops without blocking needed reads |
| read_file: small ranges widen forward to 150 lines; output is cut at a line boundary with "read lines=a-b for the rest" (it used to hide the middle) | |
| Whitespace-tolerant `replace_in_file` (re-indents to fit the file). On a miss it shows the closest region of the file | the model's `<old>` often had the wrong indentation |
| Exhausted thinking is salvaged: the tail of the reasoning is shown on the next turn with thinking off, and the model is told to act on it | overthinking had wasted about 3 min per turn with no output |
| Adaptive thinking also thinks on turns 1–2 and during read streaks or the read lock | |
| Code map in the task prompt: files, line counts, `def`/`class` lines (protected files marked) | |
| Live transcript `logs/live_<task>.txt`, written as the run goes and including thinking (tail -f it) | |
| Orphaned sandbox commands are stopped at startup | |
| Images auto-attach only from command output; generic nudges no longer mention `tamagotchi/main.py` | |

## Tests and tools
- `./venv/bin/python dev/test_worker.py`: 11 scenario tests with a fake sandbox (local subprocesses) and a scripted fake model.
- `dev/minibank-base/` plus `dev/minibank_task.txt`: a small buggy ledger with a protected PASS/FAIL checker.
- `dev/logstats-base/` plus `dev/logstats_task.txt`: a unittest-based spec task (log parser CLI).
- Both test projects were checked against a reference solution.
  Run one with `dev/run_test.sh dev/<x>-base dev/<x>_task.txt <x> --max-iterations 40`.
- `dev/show_run.py [task-stem]`: a compact timeline of a run from its JSONL log.
- `workspace/office-game/quick_check.py art|script|live`: runs sections of check_office2.py (art takes 0.25 s). It does not
  change the judge, and the task protects it.

## Runs
- minibank: PASSED in 14 turns, 88 s of model time.
- officeV11–V16: stopped and restarted as the harness changed. V16 fixed the client sprite (gen_extra_assets.py) and
  the camera.
