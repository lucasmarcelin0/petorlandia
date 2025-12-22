#!/usr/bin/env python
"""Test the timezone fix"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")

# Old way (problematic)
def utcnow_old():
    return datetime.now(timezone.utc)

# New way (fixed)
def utcnow_new():
    br_now = datetime.now(BR_TZ)
    return br_now.astimezone(timezone.utc)

# Test
now_br = datetime.now(BR_TZ)
old_result = utcnow_old()
new_result = utcnow_new()

print(f"Current time in Brazil: {now_br}")
print(f"Old utcnow() (problematic): {old_result}")
print(f"New utcnow() (fixed): {new_result}")
print()
print(f"Difference (old): {(old_result.replace(tzinfo=None) - new_result.replace(tzinfo=None))}")
print()

# Show what would be displayed
print("If we convert back to Brazil TZ:")
print(f"Old result in Brazil: {old_result.astimezone(BR_TZ)}")
print(f"New result in Brazil: {new_result.astimezone(BR_TZ)}")
