"""Parse Common Log Format lines."""
import re

LINE = re.compile(r'(\S+) \S+ \S+ \[(.*?)\] "(\S+) (\S+) \S+" (\d+) (\d+)')


def parse_line(line):
    m = LINE.match(line)
    ip, when, method, path, status, size = m.groups()
    return {"ip": ip, "time": when, "method": method, "path": path, "status": int(status), "bytes": int(size)}


def parse_file(path):
    with open(path) as f:
        return [parse_line(l) for l in f]
