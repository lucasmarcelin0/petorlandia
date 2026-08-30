## 2026-02-28 - SSRF Defense on External Image Fetching
**Vulnerability:** Server-Side Request Forgery (SSRF) when fetching external images/URLs.
**Learning:** Functions that proxy or fetch external URLs (`requests.get`) could be exploited to scan internal services or query cloud metadata endpoints (e.g. `169.254.169.254` or `127.0.0.1`).
**Prevention:** Always validate external URLs using `security.url_safe.is_url_ssrf_safe(url)` to ensure the scheme is `http`/`https` and resolved IP addresses do not belong to loopback, private, or restricted IP ranges before making outgoing requests.
