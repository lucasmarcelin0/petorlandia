from datetime import date
from dateutil.relativedelta import relativedelta

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from helpers import calcular_idade


def test_calcular_idade_months():
    nasc = date.today() - relativedelta(months=3)
    assert calcular_idade(nasc) == 3


def test_calcular_idade_years():
    nasc = date.today() - relativedelta(years=2, months=5)
    assert calcular_idade(nasc) == 2
