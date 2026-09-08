# Performance Learnings

- When extracting dictionaries dynamically via `get`, extract them once and assign them to a variable to avoid repeated lookups (e.g., `secoes = prod.get('secoes'); if not isinstance(secoes, dict): secoes = {}`).
- If extracting data on an object level via parsing nested dictionary structures repeatedly inside iterations (like extracting properties across several loop passes from `_produtos_vetsmart`), use `getattr/setattr` to store the parsed object property as an in-memory cache directly on the object instance (e.g., `_produtos_vetsmart_cache`). This prevents re-running logic that involves loops or conditionals on large structures. Wrap the `setattr` operation in `try/except` in case the object does not allow attribute setting.
