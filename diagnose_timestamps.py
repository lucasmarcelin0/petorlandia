"""
Script de diagnóstico e correção de timestamps de consultas.

Este script verifica se há inconsistências nos timestamps das consultas
e fornece informações sobre os fusos horários sendo usados.
"""

import os
import sys
from datetime import datetime,timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Consulta
from time_utils import BR_TZ, now_in_brazil, utcnow

def diagnose_timestamps():
    """Diagnostica problemas com timestamps."""
    
    with app.app_context():
        print("="*80)
        print("DIAGNÓSTICO DE TIMESTAMPS - HISTÓRICO DE CONSULTAS")
        print("="*80)
        print()
        
        # 1. Verificar horário atual do sistema
        print("1. HORÁRIOS ATUAIS:")
        print(f"   - Sistema (naive):           {datetime.now()}")
        print(f"   - Sistema timezone UTC:       {datetime.now(timezone.utc)}")
        print(f"   - Brasil (now_in_brazil):     {now_in_brazil()}")
        print(f"   - UTC (utcnow):                {utcnow()}")
        print()
        
        # 2. Verificar timestamps das consultas mais recentes
        print("2. ÚLTIMAS 10 CONSULTAS:")
        consultas = Consulta.query.order_by(Consulta.created_at.desc()).limit(10).all()
        
        for c in consultas:
            print(f"\n   Consulta #{c.id} (Animal: {c.animal.name if c.animal else 'N/A'})")
            print(f"   - created_at raw:     {c.created_at}")
            print(f"   - created_at tzinfo:   {c.created_at.tzinfo if c.created_at else 'None'}")
            
            if c.created_at:
                if c.created_at.tzinfo is None:
                    print(f"   ⚠️  AVISO: Timestamp naive (sem timezone)!")
                    # Assumir que é horário de Brasília
                    as_brazil = c.created_at.replace(tzinfo=BR_TZ)
                    print(f"   - Assumindo BR:        {as_brazil}")
                else:
                    as_brazil = c.created_at.astimezone(BR_TZ)
                    print(f"   - Convertido para BR:  {as_brazil}")
                
                print(f"   - Formatado BR:        {as_brazil.strftime('%d/%m/%Y %H:%M')}")
            
            if c.finalizada_em:
                print(f"   - finalizada_em:       {c.finalizada_em}")
                print(f"   - finalizada_em tz:    {c.finalizada_em.tzinfo if c.finalizada_em else 'None'}")
        
        print()
        print("="*80)
        print("3. RESUMO:")
        total = Consulta.query.count()
        naive_created = Consulta.query.filter(
            db.func.extract('timezone', Consulta.created_at) == None
        ).count() if hasattr(db.func, 'extract') else 0
        
        print(f"   - Total de consultas: {total}")
        print(f"   - Timezone do Brasil configurado: {BR_TZ}")
        print()
        
        print("4. VERIFICAÇÃO:")
        now_br = now_in_brazil()
        now_utc = utcnow()
        diff = now_br.utcoffset()
        print(f"   - Offset do horário de Brasília em relação ao UTC: {diff}")
        print(f"   - Horário do sistema parece estar sincronizado? ", end="")
        
        # Verificar se a diferença entre system time e BR time é razoável
        sys_time = datetime.now()
        expected_br = now_br.replace(tzinfo=None)
        time_diff = abs((sys_time - expected_br).total_seconds())
        
        if time_diff < 300:  # 5 minutos de tolerância
            print("✅ SIM")
        else:
            print(f"❌ NÃO (diferença de {time_diff/60:.1f} minutos)")
            print(f"\n   ⚠️  PROBLEMA DETECTADO:")
            print(f"   O horário do sistema está dessincronizado!")
            print(f"   Sistema: {sys_time}")
            print(f"   Esperado (Brasil): {expected_br}")
        
        print("="*80)

if __name__ == "__main__":
    diagnose_timestamps()
