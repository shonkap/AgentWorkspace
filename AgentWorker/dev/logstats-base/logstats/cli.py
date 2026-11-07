"""python3 -m logstats.cli FILE"""
import sys

from logstats.parse import parse_file
from logstats.stats import summarize

if __name__ == "__main__":
    s = summarize(parse_file(sys.argv[1]))
    print(f"total {s['total']}")
