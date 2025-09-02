# Partials

Este diretório reúne fragmentos de templates reutilizáveis.

## Estrutura

- `comuns/`
  - Componentes compartilhados entre diferentes áreas da aplicação.
  - Exemplos: formulários de endereço, listagens genéricas, grids de produtos.
- `consulta/`
  - Partials específicos do fluxo de consultas/veterinário.
  - Utilize para telas ligadas ao atendimento do animal.
- `clinica/`
  - Fragmentos usados em funcionalidades de gestão da clínica.
  - Ideal para cadastros internos, dashboards e similares.

## Boas práticas

- Prefira nomes descritivos para facilitar a descoberta dos componentes.
- Mantenha o código simples, sem regras de negócio complexas.
- Ao criar um novo partial, escolha a subpasta que melhor representa sua
  finalidade. Se for reutilizado em múltiplas áreas, coloque em `comuns/`.
- Use `{% include %}` com o caminho completo do arquivo (`partials/<pasta>/<arquivo>.html`).
- Documente comportamentos especiais diretamente no próprio template quando necessário.
