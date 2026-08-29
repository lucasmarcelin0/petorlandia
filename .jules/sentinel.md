# Sentinel Security Journal

## 2026-08-29 - SSRF Defense for Remote Image Proxies
**Vulnerability:** External image endpoints (like `/vacina-pmo/animal/<id>/photo-src`) fetched user-supplied HTTP/HTTPS image URLs without IP validation or redirect restrictions, allowing SSRF to internal services, loopback, or cloud metadata endpoints (`169.254.169.254`).
**Learning:** Checking URL schemes alone is insufficient because hostnames can resolve to internal RFC1918 IPs, loopback, or link-local addresses, and `requests.get` follows HTTP redirects by default.
**Prevention:** Use `security.url_safe.is_url_ssrf_safe` to resolve hostnames via `socket.getaddrinfo` and verify that all IP addresses are public, globally routable, and non-private before fetching, and set `allow_redirects=False` in `requests.get`.
