#!/usr/bin/env python
"""Debug script to check old consultation datetime storage."""

from app import app
from models import Consulta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")

with app.app_context():
    # Get ALL consultations ordered by ID (including old ones)
    consultas = Consulta.query.order_by(Consulta.id).limit(10).all()
    
    if consultas:
        for consulta in consultas:
            print(f"\nConsulta ID: {consulta.id}")
            print(f"created_at raw: {consulta.created_at}")
            print(f"tzinfo: {consulta.created_at.tzinfo if hasattr(consulta.created_at, 'tzinfo') else 'N/A'}")
            
            from app import format_datetime_brazil
            formatted = format_datetime_brazil(consulta.created_at)
            print(f"Displayed as: {formatted}")
    else:
        print("No consultations found")
