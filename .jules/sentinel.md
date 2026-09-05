## 2026-03-23 - CSV Formula Injection in SFA Export Module
**Vulnerability:** SFA CSV export functions (`gerar_csv_assinaturas_tcle`, `gerar_csv_exportacao_cadastro`, `gerar_csv_exportacao_analitica`) used standard `csv.DictWriter` instead of `safe_csv_dict_writer`.
**Learning:** `security.csv_safe` provides `safe_csv_dict_writer` to neutralize cells starting with formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`).
**Prevention:** All CSV generation that includes user-supplied or external data must wrap `csv.DictWriter` with `safe_csv_dict_writer` from `security.csv_safe`.

## 2026-03-30 - Open Redirect Validation with Backslashes
**Vulnerability:** Python's `urllib.parse.urlparse` does not extract netloc/scheme from paths containing backslashes (e.g. `/\attacker.com` or `\\attacker.com`), allowing open redirect bypasses because modern browsers convert backslashes to forward slashes.
**Learning:** Checking `parsed_next.netloc` alone is insufficient for relative URL sanitization in Python applications.
**Prevention:** Strictly validate that relative URLs start with a single `/`, do not start with `//` or `/\\`, and contain no backslashes `\\` anywhere in the URL string before validating scheme/netloc.

## 2026-04-06 - Incomplete Ad-Hoc PII Redaction in NFS-e Service
**Vulnerability:** `services/nfse_service.py` used an ad-hoc `_redact_sensitive_xml_text` implementation that missed formatted CPFs/CNPJs (`123.456.789-00`, `12.345.678/0001-90`), 44-digit keys, and sensitive XML tags (`InscricaoEstadual`, `ChaveAcesso`, `Secret`).
**Learning:** Ad-hoc regexes for redaction miss edge cases and diverge from the application's central redaction policy.
**Prevention:** Always delegate XML and text redaction to `security.redact` (`redact_xml` or `redact_sensitive_text`) to ensure consistent PII sanitization.
