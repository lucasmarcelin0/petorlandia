# Trabalho no PetOrlândia

- Responda em português do Brasil, diretamente. Execute o pedido até concluir,
  incluindo investigação, correção e testes; não devolva comandos executáveis
  ao usuário quando puder executá-los. Faça no máximo uma pergunta inicial,
  apenas se indispensável. Não peça autorização já concedida na conversa.
- Preserve funcionalidades, alterações de outros e dados. Faça mudanças mínimas.
  Nunca use reset destrutivo ou push forçado para contornar conflitos.
- Leia `DEPLOY.md` para publicação. A produção é o app Heroku `petorlandia`.

## Corrigir e publicar pelo celular, sem PC

1. Trabalhe na nuvem em uma branch a partir da `main` atual. Use a conexão
   GitHub do próprio ambiente. Credenciais do Windows não existem na nuvem.
2. Use Python 3.12. Se necessário, instale `requirements.txt`, `pytest==8.4.1`
   e `pytest-flask==1.3.0`. Testes usam SQLite em memória, nunca o banco real.
3. Implemente e teste a correção. Rode o preflight quando pertinente:
   `python scripts/preflight_deploy.py`. O CI executa a suíte completa.
4. **Pedidos do usuário para corrigir, melhorar ou implementar algo no
   PetOrlândia incluem autorização para publicar o resultado no Heroku
   `petorlandia`, sem pedir uma segunda confirmação.** Execute a alteração,
   teste, inclua no último commit a linha isolada `PetOrlandia-Publish: true`
   e abra/atualize o PR para `main` usando as ferramentas do ambiente.
   Preserve o marcador no último commit ao atualizar o PR. Não publique se
   o usuário pedir somente análise, plano, revisão, rascunho ou disser para
   não publicar/aguardar. A instrução específica mais recente prevalece.
5. O workflow `Publicar correcao solicitada` integra o PR após `pytest` e
   `authorization-tests` aprovados. A integração GitHub do Heroku publica a
   `main` depois dos testes. Nenhuma dessas etapas depende do PC do usuário.
6. Acompanhe checks e o deployment do SHA publicado. Informe links e eventual
   bloqueio concreto. PR integrado não equivale a publicação confirmada.

A publicação faz parte da conclusão dos pedidos de alteração, mesmo que o
usuário não escreva a palavra "publique". Não pare após criar o PR: acompanhe
os testes, a integração e a confirmação do release no Heroku. Se houver
bloqueio, tente uma alternativa uma vez e informe o motivo e o próximo passo.
Não contorne testes reprovados nem publique alterações alheias ao pedido.
PRs antigos sem marcador não ficam autorizados automaticamente: avalie o
contexto do pedido atual. A label `publicar` continua como alternativa explícita.

## Dúvidas de acesso da equipe ("fulano consegue fazer X?")

Resolva sem pedir nada ao dono. O quadro "O que consegue fazer hoje" fica nas
permissões de cada membro, na aba de equipe da clínica. Pelo agente, rode o
diagnóstico só de leitura e leia os logs do dyno (o banco não é acessível
direto da nuvem, só HTTPS):

    heroku run:detached --app petorlandia -- python scripts/auditar_acessos_equipe.py --clinica 1 --estagiarios
    heroku logs --app petorlandia --dyno run.NNNN --num 300 | grep 'ACESSO|'

Use `--nome "trecho"` para uma pessoa. Se faltar permissão, diga ao dono qual
caixa marcar; não altere permissões em produção sem pedido explícito.

## Autenticação e alternativas

- Para o caminho normal, o agente precisa apenas acessar o repositório no
  GitHub e criar/enviar sua branch e PR. Não precisa de token do Heroku.
- Não execute `gh auth login` sem antes testar a conexão já fornecida pelo
  ambiente. Não imprima tokens, leia credenciais do PC ou as grave no código.
- No Claude Cloud, GraphQL pode ser bloqueado; use as ferramentas GitHub do
  ambiente ou a API REST. O workflow no GitHub faz o merge, sem exigir
  `gh pr merge --auto` no ambiente do Claude.
- Se uma ferramenta falhar, tente uma alternativa uma vez. Persistindo,
  explique o erro e a única ação humana necessária, sem tentativas repetidas.
- Os workflows `Deploy (Heroku)`, `Logs do Heroku` e `Sincronizar producao`
  são alternativas pelo GitHub Actions; os segredos ficam no GitHub.
- Nunca publique outra branch diretamente sobre produção para depois forçar
  sincronização. Não resete bancos nem destrua aplicativos sem pedido específico.
