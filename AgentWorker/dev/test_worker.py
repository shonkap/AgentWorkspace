#!/usr/bin/env python3
"""Unit/scenario tests for worker.py with a fake sandbox (local subprocesses in a temp dir standing in for /workspace)
and a scripted fake model. Run: ./venv/bin/python dev/test_worker.py   (from AgentWorker/)"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import worker as W  # noqa: E402


class FakeContainer:
    def __init__(self, root):
        self.root = root

    def put_archive(self, directory, data):
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(self.root + directory, filter="data")
        return True

    def exec_run(self, cmd, workdir=None, environment=None):
        raise AssertionError("not used")


class Sandbox:
    """Maps container paths (/workspace/...) to a temp dir by rewriting absolute paths in argv."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(self.tmp + "/workspace", exist_ok=True)

    def map(self, s):
        return s.replace("/workspace", self.tmp + "/workspace") if isinstance(s, str) else s

    def cexec(self, args, workdir=None, timeout=None, env=None):
        args = [self.map(a) for a in args]
        if args and args[0] == "git":
            return 1, "no git in tests"
        p = subprocess.run(args, cwd=self.map(workdir) if workdir else None, capture_output=True, text=True,
                           env={**os.environ, **(env or {})}, timeout=timeout or 60)
        out = (p.stdout + p.stderr).replace(self.tmp, "")
        return p.returncode, out


class FakeModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages, options, think=None):
        self.seen.append([dict(m) for m in messages])
        if messages and messages[0]["role"] == "system" and "budget questions" in messages[0]["content"]:
            return {"message": {"content": "<turns_left>3</turns_left> almost"}}
        if messages and messages[0]["role"] == "system" and "progress notes" in messages[0]["content"]:
            return {"message": {"content": "LEARNED: x\nPLAN: y"}}
        reply = self.replies.pop(0) if self.replies else "<list_dir/>"
        return {"message": {"content": reply}, "done_reason": "stop", "eval_count": 10, "eval_duration": 1e8}


def make_env(test, files, replies, **cfg):
    sb = Sandbox()
    test.addCleanup(shutil.rmtree, sb.tmp, True)
    W.CFG.workspace_dir = sb.tmp + "/q"
    W.CFG.sandbox_dir = sb.tmp + "/workspace"
    W.CFG.ensure_dirs()
    W.CFG.use_llm_auditor = False
    W.CFG.use_git = False
    W.CFG.fix_ownership = False
    W.CFG.ask_turns_left = False
    W.CFG.notes_every = 0
    for k, v in cfg.items():
        setattr(W.CFG, k, v)
    W.cexec = sb.cexec
    fc = FakeContainer(sb.tmp)
    W.docker_client = type("D", (), {"containers": type("C", (), {"get": staticmethod(lambda name: fc)})()})()
    model = FakeModel(replies)
    W.heavy_chat = model
    W.fast_client = None
    for path, text in files.items():
        full = f"{sb.tmp}/workspace/proj/{path}"
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
    return sb, model


def task_file(sb, text):
    path = f"{sb.tmp}/q/task.txt"
    with open(path, "w") as f:
        f.write(text)
    return path


CHECK = """import sys
v = open('val.txt').read().strip() if __import__('os').path.exists('val.txt') else ''
for i in range(20): print(f'PASS  check {i}')
print('PASS  val exists' if v else 'FAIL  val exists  ->  write val.txt')
ok = v == '42'
print('PASS  val is 42' if ok else f'FAIL  val is 42  ->  got {v!r}')
sys.exit(0 if ok else 1)
"""


class Tests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: getattr(W.CFG, k) for k in vars(W.CFG)}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(W.CFG, k, v)

    def test_compress_output(self):
        text = "\n".join(["== a =="] + [f"PASS  x{i}" for i in range(30)] + ["FAIL  y  ->  bad"] + ["PASS  z"])
        out = W.compress_output(text)
        self.assertIn("FAIL  y  ->  bad", out)
        self.assertIn("[30 passing line(s) hidden]", out)
        self.assertNotIn("PASS  x3", out)
        self.assertEqual(W.compress_output("PASS a\nFAIL b"), "PASS a\nFAIL b")
        ut = "\n".join([f"test_{i} (m.T.test_{i}) ... ok" for i in range(10)] + ["test_x (m.T) ... FAIL"])
        self.assertIn("... FAIL", W.compress_output(ut))
        self.assertIn("10 passing", W.compress_output(ut))

    def test_fuzzy_replace(self):
        f = "def a():\n    # Body/torso\n    draw(x, y+20+ao[0])\n    more()\n"
        self.assertEqual(W.fuzzy_replace(f, "    # Body/torso\n        draw(x, y+20+ao[0])", "    # Body\n        draw(x, y+20)"),
                         ("def a():\n    # Body\n    draw(x, y+20)\n    more()\n", 2))
        self.assertEqual(W.fuzzy_replace(f, "# Body/torso\ndraw(x, y+20+ao[0])", "if q:\n    draw(x, y)"),
                         ("def a():\n    if q:\n        draw(x, y)\n    more()\n", 2))
        self.assertIn("most similar part", W.fuzzy_replace(f, "    draw(x, y+21+ao[0])", "z"))
        self.assertIn("matches 2 places", W.fuzzy_replace("  a\nb\n  a\n", "a", "c"))

    def test_success_and_auto_verify(self):
        sb, model = make_env(self, {"check.py": CHECK}, [
            "PLAN: run\n<run_command>python3 check.py</run_command>",
            '<write_file path="val.txt">41</write_file>',          # edit-only turn: harness runs the check itself
            '<write_file path="val.txt">42</write_file>',          # edit-only again: auto-verify passes -> complete
        ])
        ok, reason, _ = W.run_task(task_file(sb, "WORKDIR: proj\nPROTECT: check.py\nmake val 42\nVERIFY: python3 check.py"), 1)
        self.assertTrue(ok, reason)
        self.assertIn("re-ran the checks", reason)
        third_prompt = model.seen[2][-1]["content"]
        self.assertIn("AUTO-CHECK", third_prompt)
        self.assertIn("got '41'", third_prompt)
        self.assertNotIn("PASS  check 3", third_prompt)

    def test_protected_file(self):
        sb, model = make_env(self, {"check.py": CHECK}, [
            '<write_file path="check.py">print("ALL PASS")</write_file>',
            "<run_command>echo 'import sys; sys.exit(0)' > check.py</run_command>",
            "<run_command>cat check.py | head -3</run_command>",
        ], max_iterations=3, status_every=0)
        ok, reason, _ = W.run_task(task_file(sb, "WORKDIR: proj\nPROTECT: check.py\nx\nVERIFY: python3 check.py"), 1)
        self.assertFalse(ok)
        self.assertIn("REFUSED", model.seen[1][-1]["content"])
        self.assertIn("restored the originals", model.seen[2][-1]["content"])
        with open(f"{sb.tmp}/workspace/proj/check.py") as f:
            self.assertEqual(f.read(), CHECK)

    def test_read_dedup_and_lock(self):
        sb, model = make_env(self, {"check.py": CHECK, "a.py": "x = 1\n"},
                             ['<read_file path="a.py"/>'] * 4 + ['<run_command>true</run_command>', '<read_file path="a.py"/>', '<write_file path="b.txt">1</write_file>', '<read_file path="a.py"/>'],
                             max_iterations=8, status_every=0, readonly_nudge=3)
        W.run_task(task_file(sb, "WORKDIR: proj\nx\nVERIFY: python3 check.py"), 1)
        self.assertIn("x = 1", model.seen[1][-1]["content"])
        self.assertIn("UNCHANGED", model.seen[2][-1]["content"])
        self.assertIn("LOCKED", model.seen[3][-1]["content"])
        self.assertIn("REFUSED: re-reading files and list_dir are locked", model.seen[4][-1]["content"])
        self.assertIn("REFUSED: re-reading files and list_dir are locked", model.seen[6][-1]["content"])   # a command does not unlock

    def test_status_uses_cache(self):
        sb, model = make_env(self, {"check.py": CHECK}, ["<run_command>python3 check.py</run_command>"] + ["<list_dir/>"] * 5,
                             max_iterations=4, status_every=2, auto_verify_seconds=0, initial_status=False)
        events = []
        orig = W.EventLog.emit
        W.EventLog.emit = lambda self_, ev, **kw: events.append((ev, kw))
        self.addCleanup(setattr, W.EventLog, "emit", orig)
        W.run_task(task_file(sb, "WORKDIR: proj\nx\nVERIFY: python3 check.py"), 1)
        verifies = [kw for ev, kw in events if ev == "verify"]
        self.assertTrue(verifies and all(kw.get("cached") for kw in verifies), verifies)

    def test_lock_allows_unread_file(self):
        sb, model = make_env(self, {"check.py": CHECK, "a.py": "x = 1\n", "b.py": "y = 2\n"},
                             ['<read_file path="a.py"/>'] * 3 + ['<read_file path="b.py"/>'],
                             max_iterations=5, status_every=0, readonly_nudge=2, initial_status=False)
        W.run_task(task_file(sb, "WORKDIR: proj\nx\nVERIFY: python3 check.py"), 1)
        self.assertIn("REFUSED", model.seen[3][-1]["content"])
        self.assertIn("y = 2", model.seen[4][-1]["content"])

    def test_read_coverage_and_protected_cap(self):
        big = "".join(f"line{i}\n" for i in range(1, 501))
        sb, model = make_env(self, {"check.py": CHECK, "big.py": big, "judge.py": big},
                             ['<read_file path="big.py" lines="1-150"/>', '<read_file path="big.py" lines="10-20"/>',
                              '<read_file path="big.py" lines="151-300"/>', '<read_file path="judge.py" lines="1-150"/>',
                              '<read_file path="judge.py" lines="151-400"/>', '<read_file path="judge.py" lines="300-450"/>'],
                             max_iterations=7, status_every=0, readonly_nudge=99, initial_status=False)
        W.run_task(task_file(sb, "WORKDIR: proj\nPROTECT: judge.py\nx\nVERIFY: python3 check.py"), 1)
        r = [m[-1]["content"] for m in model.seen[1:]]
        self.assertIn("line150", r[0])
        self.assertIn("UNCHANGED", r[1])
        self.assertIn("line300", r[2])
        self.assertIn("lines 151-200 of 500", r[4])
        self.assertNotIn("line201", r[4])
        self.assertIn("REFUSED", r[5])

    def test_quick_check_after_edit(self):
        sb, model = make_env(self, {"check.py": CHECK}, ['<write_file path="val.txt">7</write_file>', "<list_dir/>"],
                             max_iterations=2, status_every=0, initial_status=False, auto_verify_seconds=0)
        W.run_task(task_file(sb, "WORKDIR: proj\nx\nQUICKCHECK: cat val.txt\nVERIFY: python3 check.py"), 1)
        self.assertIn("QUICK checks", model.seen[0][1]["content"])
        self.assertIn("QUICK CHECK run by the harness after your edit: cat val.txt\nExit Code: 0\n7", model.seen[1][-1]["content"])
        self.assertNotIn("QUICKCHECK", model.seen[0][1]["content"])

    def test_initial_status_and_code_map(self):
        sb, model = make_env(self, {"check.py": CHECK, "lib.py": "class Foo:\n    def bar(self):\n        pass\n"},
                             ["<list_dir/>"], max_iterations=1, status_every=0)
        W.run_task(task_file(sb, "WORKDIR: proj\nPROTECT: check.py\nx\nVERIFY: python3 check.py"), 1)
        first = model.seen[0]
        task_msg, last = first[1]["content"], first[-1]["content"]
        self.assertIn("CODE MAP", task_msg)
        self.assertIn("    2:    def bar(self):", task_msg)
        self.assertIn("check.py (7 lines)  [PROTECTED", task_msg)
        self.assertIn("AUTHORITATIVE STATUS", last)
        self.assertIn("val exists -> write val.txt", last)


if __name__ == "__main__":
    unittest.main(verbosity=2)
