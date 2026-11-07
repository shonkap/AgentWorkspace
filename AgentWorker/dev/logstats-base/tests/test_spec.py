"""Acceptance tests for logstats. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from logstats.parse import parse_file, parse_line  # noqa: E402
from logstats.stats import summarize  # noqa: E402

LOG = """203.0.113.9 - - [07/Nov/2026:10:00:01 +0000] "GET /index.html?ref=x HTTP/1.1" 200 5120
203.0.113.9 - - [07/Nov/2026:10:00:02 +0000] "GET /about HTTP/1.1" 200 1024

198.51.100.4 - - [07/Nov/2026:10:00:03 +0000] "GET /index.html HTTP/1.1" 200 2048
this is not a log line
198.51.100.4 - - [07/Nov/2026:10:00:04 +0000] "GET /missing HTTP/1.1" 404 -
192.0.2.1 - - [07/Nov/2026:10:00:05 +0000] "POST /about HTTP/1.1" 500 0
192.0.2.1 - - [07/Nov/2026:10:00:06 +0000] "GET /index.html HTTP/1.1" 200 2048
"""


def write_log(text=LOG):
    f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    f.write(text)
    f.close()
    return f.name


def cli(*args):
    return subprocess.run([sys.executable, "-m", "logstats.cli", *args], capture_output=True, text=True, cwd=ROOT, timeout=30)


class TestParse(unittest.TestCase):
    def test_fields(self):
        r = parse_line('203.0.113.9 - - [07/Nov/2026:10:00:01 +0000] "GET /a HTTP/1.1" 200 512')
        self.assertEqual(r, {"ip": "203.0.113.9", "time": "07/Nov/2026:10:00:01 +0000", "method": "GET", "path": "/a",
                             "status": 200, "bytes": 512})

    def test_query_removed(self):
        self.assertEqual(parse_line('1.2.3.4 - - [x] "GET /p?q=1&r=2 HTTP/1.1" 200 1')["path"], "/p")

    def test_dash_bytes(self):
        self.assertEqual(parse_line('1.2.3.4 - - [x] "GET /p HTTP/1.1" 304 -')["bytes"], 0)

    def test_garbage_is_none(self):
        self.assertIsNone(parse_line("garbage"))
        self.assertIsNone(parse_line(""))

    def test_parse_file_counts_bad(self):
        path = write_log()
        try:
            records, bad = parse_file(path)
        finally:
            os.unlink(path)
        self.assertEqual((len(records), bad), (6, 1))


class TestStats(unittest.TestCase):
    def setUp(self):
        path = write_log()
        self.records, _ = parse_file(path)
        os.unlink(path)

    def test_totals(self):
        s = summarize(self.records)
        self.assertEqual(s["total"], 6)
        self.assertEqual(s["bytes_total"], 10240)
        self.assertEqual(s["unique_ips"], 3)
        self.assertEqual(s["by_status"], {200: 4, 404: 1, 500: 1})

    def test_error_rate(self):
        self.assertEqual(summarize(self.records)["error_rate"], 0.167)
        self.assertEqual(summarize([])["error_rate"], 0.0)

    def test_top_paths(self):
        self.assertEqual(summarize(self.records)["top_paths"], [["/index.html", 3], ["/about", 2], ["/missing", 1]])
        self.assertEqual(summarize(self.records, top=1)["top_paths"], [["/index.html", 3]])

    def test_top_ties_by_name(self):
        recs = [{"ip": "a", "time": "", "method": "GET", "path": p, "status": 200, "bytes": 0} for p in ("/b", "/a", "/c")]
        self.assertEqual(summarize(recs, top=2)["top_paths"], [["/a", 1], ["/b", 1]])


class TestCli(unittest.TestCase):
    def test_text_output(self):
        path = write_log()
        try:
            r = cli(path)
        finally:
            os.unlink(path)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertEqual(r.stdout.strip().splitlines(), [
            "total 6", "bad 1", "bytes 10240", "errors 0.167", "unique_ips 3",
            "status 200 4", "status 404 1", "status 500 1",
            "top /index.html 3", "top /about 2", "top /missing 1"])

    def test_top_option(self):
        path = write_log()
        try:
            r = cli(path, "--top", "1")
        finally:
            os.unlink(path)
        self.assertEqual([l for l in r.stdout.splitlines() if l.startswith("top ")], ["top /index.html 3"])

    def test_json(self):
        path = write_log()
        try:
            r = cli(path, "--json")
        finally:
            os.unlink(path)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        data = json.loads(r.stdout)
        self.assertEqual(data["bad"], 1)
        self.assertEqual(data["by_status"], {"200": 4, "404": 1, "500": 1})
        self.assertEqual(list(data), sorted(data))

    def test_missing_file(self):
        r = cli("/nonexistent/file.log")
        self.assertEqual(r.returncode, 2)
        self.assertIn("error: cannot read /nonexistent/file.log", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
