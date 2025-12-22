#!/usr/bin/env python
"""Debug script to check consultation datetime storage."""

from app import app
from models import Consulta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")

with app.app_context():
    # Get recent consultations
    consultas = Consulta.query.order_by(Consulta.id.desc()).limit(5).all()
    
    if consultas:
        for consulta in consultas:
            print(f"\nConsulta ID: {consulta.id}")
            print(f"created_at raw value: {consulta.created_at}")
            print(f"created_at type: {type(consulta.created_at)}")
            print(f"created_at tzinfo: {consulta.created_at.tzinfo}")
            
            # Show what format_datetime_brazil would return
            from app import format_datetime_brazil
            formatted = format_datetime_brazil(consulta.created_at)
            print(f"format_datetime_brazil output: {formatted}")
            
            # Show if it was stored with UTC timezone
            if consulta.created_at.tzinfo:
                print(f"As UTC: {consulta.created_at.isoformat()}")
                print(f"As BR_TZ: {consulta.created_at.astimezone(BR_TZ).isoformat()}")
    else:
        print("No consultations found")
