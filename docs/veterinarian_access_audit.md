# Auditoria de permissões para veterinários

## Rotas protegidas pelo campo `User.worker == "veterinario"`

- Upload e exclusão de documentos de animais exigem que o usuário seja marcado como trabalhador veterinário para enviar ou remover arquivos clínicos.【F:app.py†L2098-L2235】
- A finalização, agendamento de retornos e exclusão de consultas clínicas dependem apenas do valor `worker` para conceder acesso às ações médicas.【F:app.py†L2365-L2703】
- Fluxos de gestão de tutores (listagem, atualização e remoção) são controlados pelo valor `worker`, permitindo acesso a veterinários ou colaboradores sem checar a existência do registro em `Veterinario`.【F:app.py†L4080-L4237】
- Operações sobre dados médicos como prescrição, vacinas, rações e blocos de exames utilizam o campo `worker` para restringir o uso, sem validar o relacionamento `Veterinario`.【F:app.py†L4452-L5833】
- Recursos de logística e agenda (entregas, pedidos e listagens de consultas administrativas) avaliam apenas `worker` para conceder privilégios, mesmo quando a lógica posteriormente assume a existência de um perfil de veterinário.【F:app.py†L5933-L6713】【F:app.py†L8133-L9718】

## Rotas que exigem a relação `User.veterinario`

- Geradores de termos e relatórios clínicos utilizam diretamente os dados do relacionamento `current_user.veterinario`, sem verificar o campo `worker`.【F:app.py†L1918-L1959】
- O painel "Minha Clínica" atualiza a clínica vinculada ao registro `Veterinario` do usuário, mesmo quando não há confirmação do campo `worker` como veterinário.【F:app.py†L2848-L2897】
- Context processors responsáveis por contadores (exames pendentes, consultas pendentes e convites de clínica) dependem da presença do objeto `current_user.veterinario` para calcular resultados.【F:app.py†L569-L655】

## Rotas que misturam os dois critérios

- Permissões de gerenciamento de clínicas, especialidades e agenda de veterinários combinam verificações de `worker` com a presença do registro `Veterinario`, refletindo a falta de um padrão único de autenticação para o papel de veterinário.【F:app.py†L2900-L4049】【F:app.py†L8133-L9718】

## Proposta de padronização

1. **Criar um helper único** — Implementar, por exemplo, `helpers.is_veterinarian(user)` que retorne `True` apenas quando o usuário tiver `worker == "veterinario"` *e* um registro associado em `Veterinario`. Esse helper pode ser reutilizado em rotas, context processors e templates para garantir consistência.
2. **Normalizar os dados** — Criar uma migração que assegure que todos os usuários com `worker == "veterinario"` possuam um registro correspondente em `Veterinario`, e vice-versa. Isso reduz divergências entre fonte de verdade e relacionamento.
3. **Aplicar decorators ou mixins de permissão** — Com o helper disponível, definir um decorator (`@veterinarian_required`) que centralize a lógica de acesso e substitua checagens manuais espalhadas pelo código. Isso melhora a legibilidade e facilita ajustes futuros.
4. **Atualizar templates e context processors** — Revisar trechos que consultam apenas `current_user.veterinario` ou apenas `worker`, substituindo pela checagem unificada para evitar comportamentos inconsistentes em diferentes partes do site.
