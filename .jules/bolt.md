# Bolt's Journal

## 2026-08-31 - Pre-compiling Regex Patterns in Posology and Jinja Filter Hot Paths
**Learning:** In PetOrlandia, posology normalization (`services/posologia_normalizacao.py`) and Jinja species/datetime filters (`template_filters.py`) are executed frequently during catalog searches, monography displays, and template rendering. Passing raw string regexes to `re.sub`/`re.search`/`re.finditer` causes redundant regex parsing and compilation on every single execution.
**Action:** Always pre-compile module-level regexes into `re.compile` objects when defining text parsing tables or filter utilities.
## 2025-05-20 - Fast-path short-circuiting for string accent stripping
**Learning:** In string processing helpers like `_strip_accents`, checking `value.isascii()` to bypass `unicodedata.normalize("NFD", value)` and character category loops on pure ASCII strings provides a ~40% execution speedup.
**Action:** When performing Unicode normalization or accent stripping across large collections of text, check for ASCII pre-conditions first to short-circuit non-accented inputs safely.

## 2026-09-03 - Pre-computing Product Tokens in Prescription-to-Store Matching
**Learning:** In `services/prescription_store.py`, `build_prescription_offers` matched prescription lines against all sellable catalog products by re-tokenizing and re-parsing strengths for each product inside the inner loop for every prescription item. Pre-extracting tokens and strengths once per catalog product reduced `build_prescription_offers` execution time by ~60%.
**Action:** When performing cross-matching between two collections (e.g. prescription lines and store products), pre-tokenize and pre-extract properties for the candidates once before entering nested loops.
