"""Re-seed do protocolo Mastite/Pseudociese para aplicar correcoes."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import app
from extensions import db
from scripts.seed_protocolos_notas import seed as seed_fn

with app.app_context():
    result = seed_fn(db.session, apply=True, only_names=['Mastite / Pseudociese em cadelas'])
    print(result)
