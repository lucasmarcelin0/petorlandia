# CORREÇÃO DAS MIGRAÇÕES DO BANCO DE DADOS

Data: 22/12/2025
Status: ✅ RESOLVIDO

## PROBLEMA

Ao executar `flask db heads`, o sistema retornava o erro:
```
KeyError: '3b4c5d6e7f80'
Revision 3b4c5d6e7f80 referenced from 3b4c5d6e7f80 -> d5e2c9a1c3f4, Add veterinarian settings table is not present
```

## CAUSA

A migração `d5e2c9a1c3f4_add_veterinarian_settings_table.py` estava referenciando uma migração anterior (`3b4c5d6e7f80`) que **não existia** no diretório de migrações.

## SOLUÇÃO APLICADA

**Arquivo**: `migrations/versions/d5e2c9a1c3f4_add_veterinarian_settings_table.py`

**Mudança**: Corrigido o `down_revision` para apontar para migração existente:
- **Antes**: `down_revision = '3b4c5d6e7f80'` ❌
- **Depois**: `down_revision = '6bb436fe2061'` ✅

## CADEIA DE MIGRAÇÕES ATUAL

```
6bb436fe2061 (initial_migration)
    ↓
d5e2c9a1c3f4 (add_veterinarian_settings_table) ← CORRIGIDO
    ↓
    ├─→ e1b9a8e9d0f1 (add_data_share_audit)
    │       ↓
    │   1f3f1a5e660d (timezone_aware_datetimes) [HEAD]
    │
    └─→ c49321bb88a2 (add_saved_by_to_bloco_prescricao) [HEAD]
```

## OBSERVAÇÃO: DUAS HEADS

O sistema atualmente tem **duas heads** (pontas) na cadeia de migrações, o que significa que há uma bifurcação:
- Head 1: `1f3f1a5e660d` (timezone_aware_datetimes)
- Head 2: `c49321bb88a2` (add_saved_by_to_bloco_prescricao)

Ambas derivam de `d5e2c9a1c3f4` mas seguiram caminhos diferentes.

### Isso é um problema?

**Não necessariamente**, mas pode causar confusão. Se quiser manter ambas, o Alembic irá aplicá-las. Se preferir ter uma cadeia linear, você pode:

1. Mesclar as heads criando uma nova migração que depende de ambas, OU
2. Continuar assim se as mudanças não conflitarem

## TESTE

Execute `flask db heads` ou use o comando direto do alembic para verificar:

```bash
python -c "import sys; sys.path.insert(0, '.'); from alembic.config import Config; from alembic import command; cfg = Config('migrations\\alembic.ini'); cfg.set_main_option('script_location', 'migrations'); command.heads(cfg, verbose=True)"
```

**Resultado**: Agora funciona sem erros! ✅

## PRÓXIMOS PASSOS (OPCIONAL)

Se quiser aplicar as migrações pendentes:
```bash
flask db upgrade
```

Ou se preferir mesclar as duas heads em uma única:
```bash
flask db merge heads -m "merge timezone and saved_by changes"
```

---

**Status**: Problema resolvido! O sistema de migrações está funcionando corretamente.
