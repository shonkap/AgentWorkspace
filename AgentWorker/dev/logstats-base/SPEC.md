# logstats spec

Input: an access log in Common Log Format, e.g.
`203.0.113.9 - - [07/Nov/2026:10:00:01 +0000] "GET /index.html?ref=x HTTP/1.1" 200 5120`

## parse.py
- `parse_line(line)` returns a dict with ip, time, method, path, status (int), bytes (int).
  - `path` has the query string removed (`/index.html?ref=x` -> `/index.html`).
  - bytes `-` means 0.
  - A line that does not match (garbage, empty) returns `None` instead of raising.
- `parse_file(path)` returns `(records, bad_lines)` where bad_lines is the number of non-empty lines that returned None.
  Blank lines are skipped and not counted as bad.

## stats.py
`summarize(records, top=3)` returns a dict:
- `total`: number of records
- `by_status`: {status: count}
- `bytes_total`: sum of bytes
- `error_rate`: share of records with status >= 500, rounded to 3 decimals (0.0 when there are no records)
- `top_paths`: list of [path, count] for the `top` most requested paths, most requested first; ties sorted by path name
- `unique_ips`: number of distinct ips

## cli.py
`python3 -m logstats.cli FILE [--top N] [--json]`
- default output, one item per line:
  ```
  total 6
  bad 1
  bytes 10240
  errors 0.167
  unique_ips 3
  status 200 4
  status 404 1
  status 500 1
  top /index.html 3
  top /about 2
  top /missing 1
  ```
  (status lines sorted by status code; top lines in summarize order)
- `--json` prints `summarize(...)` plus `"bad": N` as JSON with sorted keys (status keys as strings), nothing else.
- missing file: print `error: cannot read FILE` to stderr and exit with code 2.
