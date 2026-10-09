# Protocolo de Operação e Diretrizes de Engenharia para o Jules

Este documento define as regras mandatórias de operação, controle de qualidade, higiene de commits e diretrizes para o agente Google Jules (e suas personas **Sentinel**, **Bolt** e **Palette**) no repositório `petorlandia`.

---

## 1. Regras de Higiene de Git e Mudanças Cirúrgicas

1. **Preservação de Line Endings (CRLF / LF)**:
   - Antes de efetuar qualquer commit, execute `git diff --stat`.
   - **Regra do Churn Zero:** Nunca permita que um arquivo inteiro (ex.: `app.py`) tenha centenas ou milhares de linhas alteradas unicamente por conversão de quebras de linha (`\r\n` vs `\n`). O commit deve tocar estritamente as linhas modificadas.
   - Caso um editor ou ferramenta altere line endings do arquivo, desfaça e aplique as alterações preservando a terminação existente.

2. **Prevenção de Churn e Idempotência (Anti-Thrashing)**:
   - Antes de iniciar uma tarefa ou propor um branch, verifique se já existem branches remotos recentes (`git branch -r`) ou commits recentes no histórico (`git log -n 20`) atuando sobre o mesmo arquivo, função ou componente.
   - Não gere PRs duplicados ou micro-variações da mesma otimização sucessivamente.
   - Se uma melhoria foi sugerida e aguarda revisão, não gere um novo branch similar a menos que haja nova informação de contexto ou correção explícita solicitada.

3. **Padronização da Memória (.jules/)**:
   - Todo arquivo de memória/diário deve residir exclusivamente no diretório `.jules/` (com todas as letras minúsculas).
   - O nome dos diários deve seguir o padrão: `bolt.md` (performance), `palette.md` (acessibilidade/UI), `sentinel.md` (segurança).
   - Mantenha datas reais e precisas nas entradas de diário (formato `YYYY-MM-DD`).

---

## 2. Diretrizes Específicas por Persona

### 2.1. 🛡️ Sentinel (Segurança)

1. **Sanitização de Redirecionamentos (Open Redirect - CWE-601)**:
   - Ao redirecionar com base em `request.referrer` ou parâmetros como `next`, utilize sempre `_sanitize_login_next_url(url, fallback=...)`.
   - Certifique-se de que o `fallback` seja uma rota válida e contextualizada (ex.: voltar à ficha do animal em vez de apenas para a home).

2. **Proteção contra SSRF e DNS Rebinding (TOCTOU - CWE-918)**:
   - Para downloads ou requisições HTTP externas com URLs fornecidas pelo usuário ou via API externa (ex.: ChatGPT/MCP), utilize `safe_fetch_url` de `security.url_safe` em vez de chamar `is_url_ssrf_safe` seguido de `requests.get`.
   - Não adicione verificações dinâmicas de SSRF com resolução DNS síncrona prévia em URLs fixas e hardcoded de APIs internas previamente homologadas (como Nominatim fixo), pois isso adiciona latência sem ganho de segurança.

3. **Proteção de Dados Pessoais (LGPD / PII)**:
   - Logs de gateways de pagamento (Mercado Pago, etc.) e integrações nunca devem conter dados abertos de clientes (e-mails, CPFs, nomes completos, telefones).
   - Utilize sempre `redact_sensitive_text` de `security.redact` ao logar payloads ou exceções provenientes de gateways.

4. **Portabilidade de Subprocessos**:
   - Nunca utilize caminhos absolutos locais do sistema de arquivos (ex.: `C:\...`) para interpretadores ou utilitários. Utilize sempre `sys.executable` ou executáveis descobertos via `PATH`.

---

### 2.2. ⚡ Bolt (Performance)

1. **Robustez de Tipos em Funções Auxiliares**:
   - Ao otimizar funções de normalização ou filtros de template (como `only_digits` ou `digits_only`), nunca assuma que o argumento recebido é exclusivamente do tipo `str`.
   - Sempre trate com segurança valores `None`, `int`, `float`, instâncias numéricas e strings vazias.
   - Valores `0` (zero numérico) não devem ser convertidos acidentalmente em string vazia `""`.

2. **Priorização de Gargalos Reais (Banco de Dados e I/O)**:
   - Priorize a eliminação de consultas N+1 e agregações de tabelas inteiras (`GROUP BY` sem filtro prévio) em detrimento de micro-otimizações redundantes em strings de 10 caracteres.
   - Ao consultar históricos ou contadores associados a coleções paginadas (ex.: busca de animais), filtre e limite primeiro a entidade principal antes de buscar agregações filhas.

3. **Compilação de Regex e Fast-Paths**:
   - Pré-compile expressões regulares em nível de módulo (`re.compile`) em rotas de processamento frequente.
   - Utilize `" ".join(s.split())` para compactação de espaços em vez de `re.sub(r"\s+", " ", s)`.
   - Utilize atalhos `.isascii()` antes de rotinas pesadas de decomposição de acentos via `unicodedata`.
   - Estas três regras valem para código novo ou que já está sendo editado por outro motivo. Elas **não são motivo para abrir PR**: a varredura do código existente está encerrada (ver seção 4).

---

### 2.3. 🎨 Palette (Acessibilidade & UX)

1. **Botões de Ícone Único (Icon-Only Buttons)**:
   - Todo botão ou link interativo contendo apenas ícone deve obrigatoriamente possuir um atributo `aria-label` descritivo.
   - O ícone visual filho (`<i>` ou `<svg>`) deve sempre conter `aria-hidden="true"` para não poluir a leitura por tecnologias assistivas.

2. **Sincronização de Estado (ARIA States)**:
   - Controles de expansão/colapso (gavetas, menus, seções retráteis) devem conter `aria-expanded` (booleano) e `aria-controls` apontando para o ID do elemento controlado, atualizados dinamicamente via JS.
   - Botões de alternância de senha devem ter `aria-pressed="false|true"` e `aria-controls` associado ao ID do input de senha.
   - Ações de cópia de texto devem ter `aria-live="polite"` e atualizar dinamicamente o `aria-label` para anunciar o sucesso ("Copiado!"), restaurando o rótulo original após timeout.

3. **Formulários e Diálogos**:
   - Sempre vincule `<label for="...">` ao `<input id="...">` correspondente.
   - Modais customizados devem declarar `role="dialog"`, `aria-modal="true"` e `aria-labelledby` apontando para o título do diálogo.

---

## 3. Triagem de 2026-10-09: o que foi fechado e por quê

Em 2026-10-09 o mantenedor fechou **160 dos 172 PRs abertos do Jules**. Quase nenhum estava errado no detalhe; foram fechados porque não acrescentavam nada à `main`.

| Motivo | PRs |
|---|---|
| O conteúdo já estava na `main`, igual ou em forma equivalente | 116 |
| Micro-otimização ou limpeza repetida, sem ganho mensurável | 30 |
| Duplicata de outro PR aberto | 8 |
| Contrariava este protocolo ou causaria regressão | 6 |

Os padrões que geraram esse volume:

- **O mesmo alvo, várias vezes.** Dez PRs para a mesma extração de dígitos (`_digits`, `only_digits`, `digits_only`), seis para `templates/partials/clinical_suggestions_panel.html`, seis para pré-compilar regex em `services/vacina_pmo_service.py`.
- **Uma ocorrência por PR.** Um `aria-label` por template, um import não usado por PR, um arquivo por correção de segurança, enquanto a mesma classe de problema continuava aberta no resto do repositório.
- **Arquivos alheios à tarefa.** Remendos diferentes em `tests/test_form_feedback_contract.js` em quase toda branch para contornar a mesma falha de outro lugar, um `.coverage` commitado, um script auxiliar na raiz e conversão de fim de linha do `app.py` inteiro (diffs de mais de 14 mil linhas).
- **Título que não corresponde ao conteúdo.** PR de "testes" que mudava comportamento de produção.

Ficaram abertos, por ainda acrescentarem algo: #1943, #1944, #1935, #1916, #1941, #1864, #1857, #1856, #1859 e #1858.

---

## 4. O que não propor de novo

1. **Micro-otimizações de string**: extração de dígitos com atalho `.isdigit()`, `re.sub` por `split`/`join`, atalho `.isascii()`, `join` com list comprehension e pré-compilação de regex. O ganho medido é de cerca de 0,5 microssegundo por chamada, invisível para qualquer usuário.
2. **`aria-label` em botões só-ícone, um template por PR.** A classe está resolvida nos templates (97 de 99 em 2026-10-09).
3. **`aria-label` em controle que tem texto visível ou rótulo preenchido por JavaScript.** O atributo substitui o nome visível para o leitor de tela.
4. **Checagem de SSRF em URL fixa** (Nominatim, Google Geocoding, ViaCEP). Recusada duas vezes; ver 2.1.2.
5. **Otimização em `scripts/`, em comandos de manutenção da CLI e em migrations.** Rodam uma vez, à mão.
6. **Refatoração sem ganho de comportamento**: quebrar função longa, trocar assinatura por dataclass, remover um import por PR.
7. **Cache em `flask.g` para localizar ou deduplicar registros.** Ele pode servir dado velho ao código seguinte da mesma requisição e não existe fora de request context.
8. **Segundo manipulador de evento para um comportamento que já existe** (por exemplo, outro script de "copiar" no mesmo botão).

---

## 5. Como um PR deve ser

1. **Uma classe de problema por PR, nunca uma ocorrência.** Varra o repositório inteiro pela mesma assinatura, corrija todas as ocorrências e deixe um guard em `tests/` (varredura estática) que falhe apontando arquivo e linha quando o padrão voltar. Confirme que o guard não é vacuoso: desfaça o conserto e veja o teste falhar. Modelos: `tests/test_csrf_form_guard.py` e `tests/test_sem_falha_silenciosa_no_front.py`.
2. **Antes de começar**, rode `git log -n 30 -- <arquivo>` e procure, nos PRs abertos e nos fechados recentes, o mesmo arquivo, função ou template. Se a ideia já está coberta, encerre a sessão sem PR.
3. **Só os arquivos da tarefa.** Nada de remendo em teste alheio, `.coverage`, script auxiliar ou troca de fim de linha. Se um teste sem relação com a tarefa falha, registre no corpo do PR e não mexa nele.
4. **Título honesto.** PR de teste ou de refatoração não altera comportamento de produção. Mudança de comportamento vai em PR próprio, com o motivo.
5. **Performance com medição real**: o tempo ou o número de consultas da rota ou do job, antes e depois. Um laço de 100 mil chamadas da função isolada não é medição.
6. **Comando de teste**: `python -m pytest tests/ -q -p no:cacheprovider`. O repositório é Python/Flask; os comandos `pnpm` do prompt padrão não se aplicam.
7. **Encerrar sem PR é um resultado válido.** Quando nada atinge este padrão, o esperado é um dia sem PR. Não baixe o critério para produzir o PR diário.

---

## 6. Direção: onde está o valor

Cada item abaixo é um PR único, no formato da seção 5. A ordem dentro de cada persona é a prioridade.

### 6.1. 🛡️ Sentinel

1. **Redirecionamento por `request.referrer`**: todo uso passa por `_sanitize_login_next_url`. Já existe um `_safe_referrer` em `blueprints/agendamentos.py`; promova-o a helper comum, aplique em todos os blueprints e adicione o guard que proíbe o uso cru.
2. **Texto de exceção devolvido ao cliente**: `except Exception` que responde `str(exc)` em JSON ou em `flash`. Um helper único que registra o erro no log e devolve mensagem genérica, mais o guard.
3. **Clientes S3 sem tempo limite**: uma configuração única do `boto3` que caiba na janela de 30 segundos do roteador do Heroku, usada por todos os clientes, mais o guard. O raciocínio está no PR #1876.
4. **Logs de gateway de pagamento**: todo payload ou resposta passa por `redact_sensitive_text`, com guard.

### 6.2. ⚡ Bolt

1. **Consultas N+1 e varreduras de tabela inteira dentro de rotas** (`Model.query.all()` em handlers e nos serviços que eles chamam). Mostre o número de consultas antes e depois.
2. **`SiteFlag` e `SiteText`**: carregar todas as chaves em uma consulta por requisição e guardar "linha ausente" com um sentinela, em vez do `default` já resolvido. A versão corrigida está no PR #1882.
3. **Versão automática dos arquivos estáticos pelo conteúdo**, no lugar do `v=` manual que hoje cobre só parte dos templates. O service worker pré-carrega algumas URLs sem versão e precisa continuar funcionando.
4. **Pico de memória do scheduler** e tamanho de resposta das rotas mais usadas.

### 6.3. 🎨 Palette

1. **`aria-hidden="true"` em todos os ícones decorativos** (`<i class="fa...">` e `<i class="bi...">`): 1.410 de 1.921 não têm. Uma troca mecânica única, mais um guard com teto que só pode descer.
2. **Associação `label for` e `id`** em todos os formulários que ainda não têm, inclusive os montados por JavaScript (o PR #1941 mostra um caso).
3. **Marcação gerada por JavaScript** (`innerHTML` e template strings em `static/` e nos templates): mesmas regras de 2.3, verificadas por guard.
