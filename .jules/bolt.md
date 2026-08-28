## 2026-08-28 - Fast-path digit guard for regex PII redaction
**Learning:** XML redaction processes every text node through multiple PII regexes (CPF, CNPJ, NFe keys). Non-numeric text nodes (names, descriptions, XML tags) cannot contain numeric PII and can skip regex parsing entirely if no digits are present.
**Action:** Always check `_DIGIT_RE.search(text)` before running regex passes for numeric PII patterns.
