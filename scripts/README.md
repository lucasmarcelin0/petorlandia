# 📜 Scripts de Manutenção

Esta pasta contém scripts úteis para manutenção, desenvolvimento e operações da aplicação PetOrlândia.

## 📋 Guia de Uso

### Para Executar um Script

```bash
# Python script
python scripts/nome_do_script.py

# Com argumentos
python scripts/nome_do_script.py --option valor

# Dentro do contexto Flask
python -c "from app import app; from scripts.nome_do_script import funcao; app.app_context().push(); funcao()"
```

### Para Criar um Novo Script

1. Crie um arquivo `.py` nesta pasta
2. Use o template abaixo:

```python
"""
Script description.

Usage:
    python scripts/novo_script.py
    python scripts/novo_script.py --option valor
"""
import argparse
import logging
from app import app, db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Main script logic."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--option', default='default', help='Opção exemplo')
    args = parser.parse_args()
    
    with app.app_context():
        # Sua lógica aqui
        logger.info(f"Executando com {args.option}")

if __name__ == '__main__':
    main()
```

3. Adicione uma entrada neste README.md descrevendo o script

## 📝 Scripts Disponíveis

### Exemplo: Database Utilities
*(A ser criado conforme necessário)*

- `backup_db.py` - Realizar backup do banco de dados
- `health_check.py` - Verificar saúde da aplicação
- `fixtures/seed_data.py` - Carregar dados de teste
- `nfse_encrypt_backfill.py` - Criptografar credenciais NFS-e já existentes

## 🎯 Categorias de Scripts

- **Database**: Backup, migrations, data cleanup
- **Monitoring**: Health checks, logging, alertas
- **Development**: Fixtures, seed data, debugging
- **Operations**: Deployment, configuration, cleanup

## ✅ Checklist para Novo Script

- [ ] Docstring clara com descrição e uso
- [ ] Argumentos via argparse
- [ ] Logging apropriado (não use print)
- [ ] Tratamento de erros
- [ ] Contexto Flask quando necessário
- [ ] Entrada neste README.md
- [ ] Teste manual antes de commitar
- [ ] Sem lógica sensível (usar services/)

## 🚫 O Que NÃO Colocar Aqui

- ❌ Código de lógica de negócio (use `services/`)
- ❌ Modelos de dados (use `models/`)
- ❌ Blueprints/rotas (use `blueprints/`)
- ❌ Scripts de debug temporários (use `tests/` ou delete)
- ❌ Scripts one-off de migração (documente no git/issues)

## 💡 Exemplos de Scripts Úteis

Para exemplos de boas práticas, veja:
- `run_production.py` - Como usar argparse e Flask context
- `scheduler.py` - Como usar APScheduler
- `tests/` - Como estruturar testes ao invés de scripts

---

**Convenção**: Scripts devem ser idempotentes quando possível (rodar múltiplas vezes sem problemas).

Último atualizado: 28 de janeiro de 2026
