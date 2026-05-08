## Resumo
- [ ] Expliquei o contexto e o impacto da mudança.
- [ ] Listei riscos, mitigação e plano de rollback.

## Checklist de Segurança (obrigatório)
- [ ] **Autorização por rota validada**: confirmei `login_required` + controle de escopo/tenant/ownership em todas as rotas alteradas.
- [ ] **IDOR coberto**: validei que IDs de path/query/body só retornam/alteram recursos autorizados ao usuário atual.
- [ ] Incluí testes (ou evidências) para casos positivos e negativos de autorização (incluindo acesso indevido).
- [ ] Atualizei `docs/route_security_checklist.md` quando houve mudança em rota sensível.

## Validação
- [ ] Testes automatizados relevantes executados.
- [ ] Verificação manual em fluxos impactados.
- [ ] Não introduzi secrets/logs sensíveis.

## Evidências
- Prints/logs/links relevantes:
