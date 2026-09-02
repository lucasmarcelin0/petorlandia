## 2026-03-23 - CSV Formula Injection in SFA Export Module
**Vulnerability:** SFA CSV export functions (`gerar_csv_assinaturas_tcle`, `gerar_csv_exportacao_cadastro`, `gerar_csv_exportacao_analitica`) used standard `csv.DictWriter` instead of `safe_csv_dict_writer`.
**Learning:** `security.csv_safe` provides `safe_csv_dict_writer` to neutralize cells starting with formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`).
**Prevention:** All CSV generation that includes user-supplied or external data must wrap `csv.DictWriter` with `safe_csv_dict_writer` from `security.csv_safe`.
