## 2026-03-23 - CSV Formula Injection in SFA Export Module
**Vulnerability:** SFA CSV export functions (`gerar_csv_assinaturas_tcle`, `gerar_csv_exportacao_cadastro`, `gerar_csv_exportacao_analitica`) used standard `csv.DictWriter` instead of `safe_csv_dict_writer`.
**Learning:** `security.csv_safe` provides `safe_csv_dict_writer` to neutralize cells starting with formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`).
**Prevention:** All CSV generation that includes user-supplied or external data must wrap `csv.DictWriter` with `safe_csv_dict_writer` from `security.csv_safe`.

## 2026-03-30 - Open Redirect Validation with Backslashes
**Vulnerability:** Python's `urllib.parse.urlparse` does not extract netloc/scheme from paths containing backslashes (e.g. `/\attacker.com` or `\\attacker.com`), allowing open redirect bypasses because modern browsers convert backslashes to forward slashes.
**Learning:** Checking `parsed_next.netloc` alone is insufficient for relative URL sanitization in Python applications.
**Prevention:** Strictly validate that relative URLs start with a single `/`, do not start with `//` or `/\\`, and contain no backslashes `\\` anywhere in the URL string before validating scheme/netloc.
