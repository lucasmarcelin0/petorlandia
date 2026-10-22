# 📚 Documentação PetOrlândia

Bem-vindo à documentação centralizada do projeto PetOrlândia!

## 📖 Índice de Documentação

### 🚀 Getting Started
- [README.md](../README.md) - Visão geral do projeto e como executar
- [CONTRIBUTING.md](CONTRIBUTING.md) - Guia para contribuidores e desenvolvimento

### 🏗️ Arquitetura e Estrutura
- [ARCHITECTURE.md](ARCHITECTURE.md) - Estrutura técnica da aplicação *(a ser criado)*
- [API.md](API.md) - Referência de endpoints da API *(a ser criado)*
- [revisao_proposito_e_melhorias.md](revisao_proposito_e_melhorias.md) - Revisão detalhada do propósito da aplicação e plano de melhoria
- [multi_clinic_guide.md](multi_clinic_guide.md) - Guia de múltiplas clínicas

### 💼 Funcionalidades
- [internacao.md](internacao.md) - Internação, prescrições, medicações, plantão e impressão
- [accounting_backfill.md](accounting_backfill.md) - Recomposição de histórico contábil
- [form_feedback_checklist.md](form_feedback_checklist.md) - Checklist de feedback de formulários
- [gestao_produto.md](gestao_produto.md) - Gestão de produtos
- [nfse_municipios.md](nfse_municipios.md) - Configuração NFSe por município
- [nfse_security.md](nfse_security.md) - Segurança e rotação de chave NFS-e
- [veterinarian_access_audit.md](veterinarian_access_audit.md) - Auditoria de acesso de veterinários

### 🧪 Testes e Qualidade
- [TESTING_AND_VALIDATION.md](TESTING_AND_VALIDATION.md) - Guia de testes e validação

### 🔧 Correções e Troubleshooting
Documentação de problemas resolvidos está em [`correcciones/`](correcciones/):

- [CORRECAO_HORARIOS.md](correcciones/CORRECAO_HORARIOS.md) - Correção de horários
- [CORRECAO_MIGRATIONS.md](correcciones/CORRECAO_MIGRATIONS.md) - Correção de migrações de BD
- [HEROKU_FIX_SUMMARY.md](correcciones/HEROKU_FIX_SUMMARY.md) - Resumo de correções Heroku
- [TIMEZONE_FIX_SUMMARY.md](correcciones/TIMEZONE_FIX_SUMMARY.md) - Correção de timezones
- [CART_IMPROVEMENTS_SUMMARY.md](correcciones/CART_IMPROVEMENTS_SUMMARY.md) - Melhorias no carrinho
- [UNIFIED_HISTORY_SYNC_README.md](correcciones/UNIFIED_HISTORY_SYNC_README.md) - Sincronização de histórico

### 📊 Manutenção e Limpeza
- [CLEANUP_ANALYSIS.md](../CLEANUP_ANALYSIS.md) - Análise de limpeza do projeto

---

## 🎯 Como Usar Esta Documentação

1. **Novo no projeto?** Comece com [README.md](../README.md)
2. **Quer contribuir?** Leia [CONTRIBUTING.md](CONTRIBUTING.md)
3. **Encontrou um bug?** Veja [correcciones/](correcciones/) para problemas similares resolvidos
4. **Precisa de ajuda?** Consulte o documento específico da funcionalidade desejada

---

## 🔗 Estrutura do Projeto

```
petorlandia/
├── app.py                      # Aplicação principal
├── requirements.txt            # Dependências
├── models/                     # Modelos de dados
├── services/                   # Lógica de negócio
├── blueprints/                 # Rotas organizadas por domínio
├── static/                     # Assets (CSS, JS, imagens)
├── templates/                  # Templates HTML
├── tests/                      # Testes pytest
├── migrations/                 # Migrações Alembic
└── docs/                       # Esta documentação
    ├── correcciones/           # Histórico de correções
    └── (todos os .md acima)
```

---

## 📝 Notas Importantes

- Todos os scripts de debug foram removidos (use `tests/` para testes estruturados)
- Documentação de correções está centralizada em `docs/correcciones/`
- O projeto usa estrutura de blueprints por domínio (admin, agendamentos, loja, etc)
- Testes devem ser executados com `pytest`

---

**Último atualizado:** 28 de janeiro de 2026
