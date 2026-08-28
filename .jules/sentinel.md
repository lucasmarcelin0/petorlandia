## 2026-08-28 - CSV Formula Injection Prevention in SFA Exports
**Vulnerability:** SFA CSV export functions (`gerar_csv_exportacao_cadastro`, `gerar_csv_exportacao_analitica`, `gerar_csv_assinaturas_tcle`) used `csv.DictWriter` directly without sanitizing formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`) in user-supplied strings.
**Learning:** `security/csv_safe.py` provides `escape_csv_value` and `safe_csv_dict_writer` specifically to neutralize formula injection in exported CSV spreadsheets across PetOrlandia.
**Prevention:** All CSV export endpoints in new or existing modules must use `safe_csv_dict_writer` or `safe_csv_writer` and pass string values through `escape_csv_value`.
