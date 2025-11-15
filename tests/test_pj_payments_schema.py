import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import services.finance as finance


def test_pj_payments_schema_requires_new_columns(monkeypatch):
    finance._TABLE_COLUMN_CACHE.clear()

    def missing_plantao_horas(table_name: str):
        if table_name == 'pj_payments':
            return {'tipo_prestador'}
        return set()

    monkeypatch.setattr(finance, '_get_table_columns', missing_plantao_horas)
    assert finance.pj_payments_schema_is_ready() is False

    finance._TABLE_COLUMN_CACHE.clear()

    def full_schema(table_name: str):
        if table_name == 'pj_payments':
            return set(finance.REQUIRED_PJ_PAYMENT_COLUMNS)
        return set()

    monkeypatch.setattr(finance, '_get_table_columns', full_schema)
    assert finance.pj_payments_schema_is_ready() is True
