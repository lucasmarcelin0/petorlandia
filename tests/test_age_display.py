from datetime import date
from dateutil.relativedelta import relativedelta

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import Animal


def test_age_display_months():
    animal = Animal(name="Filhote", user_id=1, date_of_birth=date.today() - relativedelta(months=5))
    assert animal.age_display == "5 meses"
