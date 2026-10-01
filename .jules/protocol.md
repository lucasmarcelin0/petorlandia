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
