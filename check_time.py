"""
Script de diagnóstico simplificado de timestamps.

Este script verifica os horários do sistema e fusos horários configurados.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Configuração do timezone do Brasil
BR_TZ = ZoneInfo("America/Sao_Paulo")

def diagnose_timestamps():
    """Diagnostica problemas com timestamps."""
    
    print("="*80)
    print("DIAGNÓSTICO DE TIMESTAMPS - SISTEMA")
    print("="*80)
    print()
    
    # 1. Verificar horário atual do sistema
    print("1. HORÁRIOS ATUAIS DO SISTEMA:")
    sys_naive = datetime.now()
    sys_utc = datetime.now(timezone.utc)
    sys_br = datetime.now(BR_TZ)
    
    print(f"   - Sistema (naive):              {sys_naive}")
    print(f"   - Sistema em UTC:                {sys_utc}")
    print(f"   - Sistema em BR (America/SP):    {sys_br}")
    print()
    
    # 2. Verificar offset e diferenças
    print("2. ANÁLISE DE FUSOS HORÁRIOS:")
    utc_offset = sys_br.utcoffset()
    print(f"   - Offset de Brasília (UTC):      {utc_offset}")
    print(f"   - Horário atual em Brasília:     {sys_br.strftime('%d/%m/%Y %H:%M:%S')}")
    print()
    
    # 3. Comparar horários
    print("3. VERIFICAÇÃO DE SINCRONIZAÇÃO:")
    
    # Comparar naive vs BR (devem estar próximos se o sistema está configurado para BR)
    expected_br_naive = sys_br.replace(tzinfo=None)
    diff_seconds = abs((sys_naive - expected_br_naive).total_seconds())
    
    print(f"   - Diferença entre system time e BR: {diff_seconds:.1f} segundos")
    
    if diff_seconds < 300:  # 5 minutos
        print(f"   ✅ Sistema parece estar sincronizado")
    else:
        minutes = diff_seconds / 60
        print(f"   ❌ ATENÇÃO: Sistema dessincronizado ({minutes:.1f} minutos de diferença)")
        print()
        print(f"   PROBLEMA DETECTADO:")
        print(f"   - Horário do sistema:          {sys_naive.strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"   - Horário esperado (Brasília): {expected_br_naive.strftime('%d/%m/%Y %H:%M:%S')}")
        print()
        print(f"   💡 SOLUÇÃO:")
        print(f"   Execute este comando no PowerShell (como Administrador):")
        print(f"   w32tm /resync /force")
        print(f"   ")
        print(f"   Ou sincronize manualmente:")
        print(f"   1. Abra Configurações > Hora e Idioma > Data e Hora")
        print(f"   2. Clique em 'Sincronizar agora'")
    
    print()
    print("="*80)
    print("4. INFORMAÇÕES ADICIONAIS:")
    print(f"   - Timezone detectado do sistema: {datetime.now().astimezone().tzinfo}")
    print(f"   - Timezone configurado no app:   {BR_TZ}")
    print("="*80)

if __name__ == "__main__":
    diagnose_timestamps()
