"""Versioned, non-identifying municipal snapshot; no external calls at runtime."""
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / 'data' / 'entomologia'


@lru_cache(maxsize=1)
def load_entomologia():
    with (DATA_DIR / 'snapshot.json').open(encoding='utf-8') as stream:
        return json.load(stream)


@lru_cache(maxsize=1)
def load_reference_maps():
    with (DATA_DIR / 'maps' / 'manifest.json').open(encoding='utf-8') as stream:
        return json.load(stream)
