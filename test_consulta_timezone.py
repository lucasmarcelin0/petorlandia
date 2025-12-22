#!/usr/bin/env python
"""
Test script to verify timezone handling in the database.
Run this script from the project root directory.
"""
import sys
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import Flask app and models
from app import app, db
from models import Consulta, Animal, User
from time_utils import utcnow, now_in_brazil, BR_TZ

def test_timezone_handling():
    """Test that consultas are created with correct timezone handling."""
    
    with app.app_context():
        print("=" * 60)
        print("Testing Timezone Handling")
        print("=" * 60)
        
        # Test the utcnow function
        print("\n1. Testing utcnow() function:")
        utc_now = utcnow()
        br_now = now_in_brazil()
        print(f"   utcnow() returns: {utc_now}")
        print(f"   Timezone info: {utc_now.tzinfo}")
        print(f"   now_in_brazil() returns: {br_now}")
        
        # Test creating a new consulta
        print("\n2. Testing consulta creation:")
        
        # Get or create a test animal
        animal = Animal.query.first()
        user = User.query.first()
        
        if not animal or not user:
            print("   ⚠️ No animals or users in database. Skipping consulta creation test.")
            print("   Please ensure database is populated with at least one animal and user.")
            return
        
        # Create a test consulta
        test_consulta = Consulta(
            animal_id=animal.id,
            created_by=user.id,
            status='in_progress'
        )
        
        print(f"   Created consulta with created_at: {test_consulta.created_at}")
        print(f"   Timezone info: {test_consulta.created_at.tzinfo}")
        
        # Add to session (but don't commit to avoid side effects)
        db.session.add(test_consulta)
        db.session.flush()  # Flush to get the ID but don't commit
        
        print(f"   After flush, created_at: {test_consulta.created_at}")
        print(f"   Timezone info: {test_consulta.created_at.tzinfo}")
        
        # Convert to Brazil timezone
        if test_consulta.created_at:
            if test_consulta.created_at.tzinfo is None:
                test_utc = test_consulta.created_at.replace(tzinfo=timezone.utc)
            else:
                test_utc = test_consulta.created_at
            test_br = test_utc.astimezone(BR_TZ)
            print(f"   When converted to Brazil TZ: {test_br}")
        
        # Rollback to avoid saving
        db.session.rollback()
        
        print("\n3. Testing format_datetime_brazil filter:")
        from app import format_datetime_brazil
        
        # Test with a known UTC time
        test_dt_utc = datetime(2025, 12, 22, 19, 26, 0, tzinfo=timezone.utc)
        formatted = format_datetime_brazil(test_dt_utc)
        print(f"   UTC time: {test_dt_utc}")
        print(f"   Formatted as Brazil time: {formatted}")
        print(f"   Expected: 22/12/2025 16:26 (3 hours earlier)")
        
        # Test with naive datetime (should assume UTC)
        test_dt_naive = datetime(2025, 12, 22, 19, 26, 0)
        formatted_naive = format_datetime_brazil(test_dt_naive)
        print(f"\n   Naive datetime: {test_dt_naive}")
        print(f"   Formatted as Brazil time: {formatted_naive}")
        print(f"   Expected: 22/12/2025 16:26 (same conversion)")
        
        print("\n" + "=" * 60)
        print("✅ Timezone handling test complete!")
        print("=" * 60)

if __name__ == '__main__':
    test_timezone_handling()
