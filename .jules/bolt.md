## Performance Optimization: N+1 in Transaction Classification

**Issue:** An N+1 query issue occurred during the monthly transaction classification process. `classify_transactions_for_month` loops over query results (e.g., service sales, product sales, expenses) and calls `_upsert_classified_transaction` for each item. Previously, `_upsert_classified_transaction` would query the database for the existing record one by one (`ClassifiedTransaction.query.filter_by(...).one_or_none()`), causing an N+1 query problem that scaled poorly with the number of transactions.

**Optimization Strategy implemented:**
1. Implemented bulk pre-fetching: Added `_pre_fetch_classified_transactions` to fetch all existing classified transactions for the relevant clinic, month, and origin in a single query.
2. Dictionary cache lookup: Converted the fetched records into a dictionary keyed by `raw_id`.
3. Parameter injection: Updated `_upsert_classified_transaction` to optionally accept an `existing_record` argument, utilizing a sentinel `_MISSING = object()` as default to distinguish between "not provided" and "provided as None" (for when a record doesn't exist). This ensures no unnecessary database lookups occur for inserts when pre-fetching indicates the record doesn't exist.
4. Lazy load prevention: Removed `record.clinic.classified_transactions.append(record)` which could trigger a massive lazy load of the entire `classified_transactions` collection into memory just to append a new item. `db.session.add(record)` is sufficient.

**Measured Improvement:**
Measured performance improvements via `cProfile` over 1,000 inserted items and their subsequent update on an SQLite test database.
- **Insertions (Creation):** 2.63s -> 0.21s (~92% improvement)
- **Updates:** 1.20s -> 0.11s (~91% improvement)
