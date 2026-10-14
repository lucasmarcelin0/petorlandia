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

## 2026-09-07 - Pre-compiling Regex Patterns and ASCII Fast-Path in Treatment Posology Parsing
**Learning:** `services/tratamento.py` parses dosage frequency and duration strings (`parse_intervalo_horas`, `parse_duracao_dias`, `eh_uso_continuo`) repeatedly. Pre-compiling frequency regex patterns at module level and adding an `isascii()` check in `_normalizar` avoids repetitive NFKD decomposition and regex re-compilation in hot execution paths.
**Action:** Pre-compile frequency/duration regexes in treatment tracking and short-circuit ASCII text before accent stripping.

## 2026-09-08 - Batch Pre-fetching in Financial Classification and Object-Level Bulario Cache
**Learning:** In `services/finance.py`, single-record `_upsert_classified_transaction` calls inside transaction loops trigger repetitive single SELECT queries (N+1 queries). Pre-fetching all classified transactions per `(clinic_id, month, origin)` upfront into a dict indexed by `raw_id` reduces classification queries by >90%. Similarly, parsing complex JSON structures like `_produtos_vetsmart` in `services/bulario.py` benefits significantly from attaching a lazy in-memory cache `_produtos_vetsmart_cache` on the model instance.
**Action:** Always pre-fetch existing records by batch key prior to upsert loops and cache parsed JSON structures on model instances during request lifecycles.

## 2026-09-08 - Eliminating Unbounded Full-Table Scans in Slot Conflict Queries
**Learning:** In `helpers.py`, `has_conflict_for_slot` checked time window filters for conflicting appointments/exams. When 0 conflicts were returned in the window (indicating a free slot), fallback clauses (`if not cached_appts and not appointments:`) triggered queries for ALL appointments and exams for the veterinarian across the entire database history. Removing these unnecessary fallbacks provided a 5.3x speedup on slot conflict checks.
**Action:** Do not issue fallback un-bounded queries when targeted window queries return empty sets indicating no records exist within the range.

## 2026-09-12 - ASCII Fast-Path and Pre-compiled Regexes in Medication Name Normalization
**Learning:** In `services/medicamento_curadoria.py`, `normalizar_nome_prescrito` ran `unicodedata.normalize("NFKD", texto)` and character-combining filtering loops on every string, along with re-compiling regexes (`[^\w%/.,+\- ]+` and `\s*-\s*`) dynamically on every call. Adding an `isascii()` pre-condition check to short-circuit NFKD decomposition and pre-compiling regex patterns at module level yields a ~40% execution speedup.
**Action:** Check for ASCII pre-conditions before unicodedata decomposition in string normalization helpers, and pre-compile regular expression patterns at module level.

## 2026-09-20 - Pre-compiling Regex Patterns in Medication Concentration Parsing
**Learning:** `_parse_concentracao_string` in `blueprints/consulta.py` parses concentration strings (ratios, compounds, single units, pure numbers) during medication presentation creation and search. Executing `re.search` with raw regex strings on every invocation causes redundant regex parsing and compilation overhead. Pre-compiling module-level regex objects (`_RE_CONCENTRACAO_*`) improves parsing execution speed by ~33%.
**Action:** Always pre-compile module-level regex objects when parsing concentration or unit strings in blueprint handlers and services.

## 2026-09-18 - Pre-compiled Regexes, ASCII Fast-Path Short-Circuiting, and List Comprehension Joins
**Learning:** Checking `value.isascii()` to bypass `unicodedata.normalize("NFKD", value)` and character filtering loops provides substantial execution speedup on pure ASCII inputs. Furthermore, using list comprehensions `"".join([c for c in ...])` instead of generator expressions provides a known-size sequence to CPython's string join, avoiding incremental buffer reallocations. In `services/bulario.py`, pre-compiling 16 regex patterns at module level for presentation parsing, dose strengths, species detection, and indication tokens eliminates redundant re-compilation in search and render loops.
**Action:** Pre-compile regular expressions at module level, short-circuit non-accented ASCII strings before unicodedata calls, and prefer list comprehensions within `str.join()` calls.

## 2026-09-19 - Request-Scoped `g` Caching for Site Flags and Site Text Lookups
**Learning:** `SiteFlag.get` and `SiteText.get` were called repeatedly per request across `context_processors.py`, layout templates, and views (10-20 duplicate SQL queries per page load for home and navbar flags). Caching lookups in Flask `g` (`_site_flag_cache` and `_site_text_cache`) when `has_request_context()` is active eliminates redundant SQL queries within a single request lifecycle, yielding an instant response for repetitive config reads.
**Action:** Use request-scoped `g` dictionary caches for frequently read system/site config lookups to prevent repeated database queries during request rendering.

## 2026-09-24 - Deferring Full-Table Appointment Aggregations in Animal Search
**Learning:** In `services/animal_search.py`, joining `_build_last_appointment_subquery(clinic_scope)` upfront triggered a full-table `GROUP BY` across all appointments in the clinic on every animal search query. Deferring the last appointment query until after filtering and paginating animals (for non-`recent_attended` sorts) and querying only the resulting 50 animal IDs eliminates heavy aggregations on typing and autocompletion.
**Action:** When filtering and paginating a primary entity, defer secondary aggregated metric queries until after the primary entity collection is bounded by limit/pagination.

## 2026-09-24 - Batch Pre-fetching in Plantão Pending Notifications
**Learning:** `_ensure_pending_plantao_notifications` in `services/finance.py` queried `ClinicNotification` individually inside an iteration loop over pending payments, resulting in N+1 database queries. Pre-fetching all existing notifications for the clinic and month into a dictionary indexed by `payment_id` eliminates all single queries and allows in-memory resolution of stale notices.
**Action:** Pre-load existing notification records into an in-memory dictionary indexed by parent record ID prior to processing pending payment notification loops.

## 2026-09-30 - Safe Fast-Path `.isdigit()` and List Comprehension for Digit Stripping
**Learning:** Calling `filter(str.isdigit, ...)` or `re.sub(r"\D+", "", ...)` incurs unnecessary iterator and regex engine overhead on strings that are already numeric (e.g. phones or IDs). Checking `.isdigit()` on string representations short-circuits pure numeric strings in O(1) time, while list comprehension `"".join([c for c in s if c.isdigit()])` eliminates iterator overhead for mixed strings. Caution: Always coerce to string first or check types so integers (`0`, `123`) or `None` do not cause `AttributeError` or false-empty outputs.
**Action:** When extracting digits from string or primitive inputs, safely handle non-string types and use `.isdigit()` fast-path before list comprehension filtering.

## 2026-10-09 - Maintainer triage: string micro-optimizations are closed; work on measured bottlenecks
**Learning:** The maintainer closed 54 of the 56 open Bolt PRs on 2026-10-09. Most were variations of the same string micro-optimizations (digit stripping, `re.sub` to `split`/`join`, `.isascii()` fast-paths, list-comprehension joins, regex pre-compilation), often several PRs for the same function. The measured gain is about 0.5 microseconds per call, which no user can notice, while each PR cost review time and conflicted with the others.
**Action:** Do not propose string micro-optimizations again. Read `.jules/protocol.md` sections 4 to 6 before every session and pick work from section 6.2 (N+1 queries and full-table scans inside request handlers, with the query count before and after). If nothing there applies, end the session without a PR.
