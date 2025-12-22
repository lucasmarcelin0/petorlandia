#!/usr/bin/env python
"""Find consultations around 22/12/2025 14:13."""

from app import app
from models import Consulta, Animal
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func

BR_TZ = ZoneInfo("America/Sao_Paulo")

with app.app_context():
    # Find consultations from December 22, 2025
    consultas = Consulta.query.filter(
        func.date(Consulta.created_at) == datetime(2025, 12, 22).date()
    ).order_by(Consulta.created_at.desc()).all()
    
    print(f"Found {len(consultas)} consultations on 22/12/2025\n")
    
    if consultas:
        for consulta in consultas[:5]:  # Show first 5
            animal = Animal.query.get(consulta.animal_id)
            print(f"Consulta ID: {consulta.id}")
            print(f"Animal: {animal.name if animal else 'Unknown'}")
            print(f"created_at raw: {consulta.created_at}")
            print(f"tzinfo: {consulta.created_at.tzinfo}")
            
            from app import format_datetime_brazil
            formatted = format_datetime_brazil(consulta.created_at)
            print(f"Displayed as: {formatted}")
            print()
    else:
        print("No consultations found on that date")
