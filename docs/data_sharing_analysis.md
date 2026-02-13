# Análise de Compartilhamento de Dados entre Clínicas

## Visão Geral da Segregação de Dados
- A maior parte dos modelos centrais (`User`, `Animal`, `Consulta`, `Appointment`, `Orcamento` etc.) possui coluna `clinica_id`, permitindo associar registros a uma clínica específica e restringir consultas com base nesse campo.【F:models.py†L174-L975】
- O helper `current_user_clinic_id()` retorna a clínica "ativa" do usuário autenticado e é amplamente reutilizado para filtrar dados em rotas e consultas.【F:app.py†L303-L340】
- A função `ensure_clinic_access()` aborta requisições quando o usuário autenticado não pertence à clínica solicitada e é invocada em pontos críticos (ex.: visualização/edição de consultas, blocos de orçamento, agendas).【F:app.py†L418-L448】【F:app.py†L10935-L10997】【F:app.py†L11481-L11539】
- Há ainda o predicado `_user_visibility_clause()` que combina privacidade (`is_private`) com o conjunto de clínicas acessíveis ao usuário para limitar listagens de tutores e clientes.【F:app.py†L360-L409】

## Pontos com Risco de Compartilhamento entre Clínicas

### 1. Painel administrativo genérico (`/painel`)
- Qualquer usuário autenticado consegue acessar a rota `/painel`, que exibe contadores globais de usuários, animais, clínicas, consultas e prescrições sem filtro por clínica.【F:app.py†L953-L964】
- Mesmo colaboradores ou veterinários acabam visualizando estatísticas agregadas de toda a base, expondo volume e atividade de outras clínicas.

### 2. Dashboard financeiro de orçamentos (`/dashboard/orcamentos`)
- A rota requer apenas autenticação e agrega todas as consultas com orçamento, pagamentos associados e totais por cliente/animal em toda a base.【F:app.py†L3909-L3958】
- O relatório inclui nomes de tutores, animais e valores de orçamentos de clínicas distintas, caracterizando vazamento direto de dados sensíveis entre unidades.

### 3. API de pets da clínica (`/api/clinic_pets`)
- Para veterinários/colaboradores, a rota retorna todos os animais cujo `clinica_id` coincide **ou** que tenham realizado ao menos um agendamento na clínica (via `last_appt`).【F:app.py†L10355-L10424】
- Animais cuja clínica principal mudou continuam disponíveis se tiverem histórico de consulta, permitindo que a clínica antiga veja dados atualizados (nome, tutor, foto) de clientes que já migraram para outra unidade.

### 4. Visibilidade de tutores não privados
- `_user_visibility_clause()` permite listar qualquer usuário com `is_private = False`, independentemente da clínica, desde que o usuário pesquisado não esteja marcado como privado.【F:app.py†L360-L409】
- A migração que introduziu `is_private` definiu o valor `False` para todos os usuários sem `clinica_id`, ou seja, perfis não vinculados a uma clínica tornam-se visíveis globalmente.【F:migrations/versions/8c5e4d7c9b1a_add_user_privacy_flag.py†L19-L29】
- Consultas como `_get_recent_tutores()` (usada no dashboard de tutores) e listagens padrão recorrem a `_user_visibility_clause()` sem delimitar a clínica, expondo tutores "públicos" a qualquer clínica com acesso ao módulo.【F:app.py†L7384-L7499】

### 5. Seleção automática de clínica em visões administrativas
- Algumas telas administrativas, ao filtrar colaboradores ou veterinários, caem em fallback que seleciona a primeira clínica disponível quando o administrador não informa um `clinica_id`. Isso pode induzir acessos involuntários a dados de outra unidade ao alternar visões (ex.: agenda como colaborador).【F:app.py†L9486-L9517】
- Embora o perfil administrador tenha permissão ampla por design, o comportamento pode gerar confusão e risco de manipular dados errados se o admin atuar em múltiplas clínicas.

## Controles Existentes e Lacunas
- Várias rotas sensíveis (impressões de orçamentos, agendamentos por clínica, blocos de orçamento) aplicam `ensure_clinic_access`, mostrando maturidade na segregação operacional.【F:app.py†L10935-L10997】【F:app.py†L11481-L11539】
- A definição de `current_user_clinic_id()` considera apenas a clínica principal do veterinário; associações secundárias (via `Veterinario.clinicas`) só aparecem em alguns fluxos, o que pode levar usuários multiclínica a alternar manualmente o contexto para não misturar dados.
- A adição/remoção de funcionários ajusta `user.clinica_id`, garantindo que colaboradores comuns permaneçam vinculados a uma única clínica, reduzindo vazamentos acidentais.【F:app.py†L4006-L4075】

## Recomendações Prioritárias
1. **Restringir `/painel`** a administradores ou aplicar filtros por `current_user_clinic_id()` antes de exibir métricas, evitando exposição global de volumes e atividades.【F:app.py†L953-L964】
2. **Segmentar `/dashboard/orcamentos`** por clínica e por permissão, ou mover o relatório para um contexto administrativo global explicitamente controlado.【F:app.py†L3909-L3958】
3. **Rever lógica de `/api/clinic_pets`**, garantindo que somente animais com `clinica_id` vigente sejam retornados ou que dados históricos venham anonimizados ao permanecerem acessíveis pela clínica anterior.【F:app.py†L10355-L10424】
4. **Ajustar `_user_visibility_clause`/`is_private`** para que o padrão seja "visível apenas à clínica" e exigir consentimento explícito para tornar tutores públicos. Rever consultas que chamam `_user_visibility_clause()` sem escopo de clínica.【F:app.py†L360-L409】【F:app.py†L7384-L7499】【F:migrations/versions/8c5e4d7c9b1a_add_user_privacy_flag.py†L19-L29】
5. **Introduzir seleção explícita de contexto** para administradores que atuam em múltiplas clínicas ao usar visões de colaboradores/veterinários, evitando o fallback automático para a primeira clínica cadastrada.【F:app.py†L9486-L9517】

## Próximos Passos Sugeridos
- Mapear todas as rotas autenticadas sem `ensure_clinic_access` para confirmar se realmente podem operar em escopo global ou se precisam de filtros adicionais.
- Instrumentar logs/auditoria para rastrear quando usuários acessam dados fora de sua clínica e validar hipóteses de vazamento.
- Documentar claramente quais perfis possuem visão multi-clínica por design (ex.: administradores corporativos) versus quais deveriam operar estritamente no contexto da clínica ativa.

