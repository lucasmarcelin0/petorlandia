## 2026-03-30 - Open Redirect Validation with Backslashes
**Vulnerability:** Python's `urllib.parse.urlparse` does not extract netloc/scheme from paths containing backslashes (e.g. `/\attacker.com` or `\\attacker.com`), allowing open redirect bypasses because modern browsers convert backslashes to forward slashes.
**Learning:** Checking `parsed_next.netloc` alone is insufficient for relative URL sanitization in Python applications.
**Prevention:** Strictly validate that relative URLs start with a single `/`, do not start with `//` or `/\\`, and contain no backslashes `\\` anywhere in the URL string before validating scheme/netloc.
