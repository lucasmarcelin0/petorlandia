#!/usr/bin/env python
"""Debug script to check appointment timezone issues."""

from app import app
from models import Appointment
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")

with app.app_context():
    # Get the most recent appointment
    appt = Appointment.query.order_by(Appointment.id.desc()).first()
    
    if appt:
        print(f"Appointment ID: {appt.id}")
        print(f"scheduled_at value: {appt.scheduled_at}")
        print(f"scheduled_at type: {type(appt.scheduled_at)}")
        print(f"scheduled_at tzinfo: {appt.scheduled_at.tzinfo}")
        
        if appt.scheduled_at.tzinfo:
            print(f"\nConverted to BR_TZ: {appt.scheduled_at.astimezone(BR_TZ)}")
            print(f"Formatted: {appt.scheduled_at.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')}")
        else:
            print("scheduled_at is naive (no timezone)")
            
        # Show what format_datetime_brazil would return
        from app import format_datetime_brazil
        print(f"\nformat_datetime_brazil output: {format_datetime_brazil(appt.scheduled_at)}")
    else:
        print("No appointments found")
