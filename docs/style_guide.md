# Guia de Estilo PetOrlândia

Este guia consolida os tokens visuais aplicados no front-end e resume padrões de componentes para apoiar implementações futuras.

## Identidade visual

### Paleta principal

| Token | Valor | Origem | Uso recomendado |
| --- | --- | --- | --- |
| `--color-primary` | `#4e73df` | `static/style.css` | Ações primárias, destaques na navegação e badges ativos. |
| `--color-primary-emphasis` | `#3a5ccc` | `static/style.css` | Estados hover/focus de elementos primários. |
| `--color-secondary` | `#1cc88a` | `static/style.css` | Botões de sucesso, indicadores positivos. |
| `--color-danger` | `#e74a3b` | `static/style.css` | Erros, alertas críticos, ações destrutivas. |
| `--color-warning` | `#f6c23e` | `static/style.css` | Alertas de atenção com texto escuro. |
| `--color-info` | `#36b9cc` | `static/style.css` | Mensagens informativas e ícones auxiliares. |
| `--color-dark` | `#5a5c69` | `static/style.css` | Texto padrão em fundos claros. |
| `--color-light` | `#f2f5f9` | `static/style.css` | Fundo de páginas e cards neutros. |
| `--color-surface` | `#ffffff` | `static/style.css` | Painéis e containers internos. |
| `--color-body` | `#333333` | `static/style.css` | Texto base; garante contraste AA sobre `--color-surface`. |

### Gradientes e destaques complementares

| Token | Valor | Origem | Observações |
| --- | --- | --- | --- |
| `--toolbar-gradient-start` → `--toolbar-gradient-end` | `#0d6efd → #6610f2` | `static/styles.css` (`.schedule-toolbar`) | Usado na barra de ações da agenda; manter contraste com ícones brancos. |
| `.schedule-toolbar-btn--info` | `linear-gradient(135deg, #38bdf8, #60a5fa)` | `static/styles.css` | Botão informativo da agenda. |
| `.schedule-toolbar-btn--success` | `linear-gradient(135deg, #34d399, #10b981)` | `static/styles.css` | Ações de confirmação/adição de consulta. |
| `.schedule-toolbar-btn--warning` | `linear-gradient(135deg, #fbbf24, #f59e0b)` | `static/styles.css` | Solicita atenção; texto troca para `#1f2937` para contraste. |
| `.schedule-toolbar-btn--primary` | `linear-gradient(135deg, #7c3aed, #2563eb)` | `static/styles.css` | Botão destacado na agenda. |
| `.schedule-action-btn` | `linear-gradient(135deg, rgba(79, 70, 229, 0.08), rgba(59, 130, 246, 0.12))` | `static/styles.css` | Controles secundários com borda translúcida. |
| `body` (telas de consulta) | `linear-gradient(#e3f2fd, #ffffff)` | `templates/base_consulta.html` | Padrão ainda divergente da paleta principal; ver recomendações abaixo. |

## Tipografia

```css
:root {
  --font-family-sans: 'Poppins', sans-serif;
  --font-size-root: clamp(14px, 1vw + 0.5rem, 18px);
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
}
html { font-size: var(--font-size-root); }
body { font-family: var(--font-family-sans); }
```

* **Peso dos títulos:** `var(--font-weight-semibold)` aplicado em `h1–h6` garante hierarquia consistente.
* **Base_consulta:** telas como `novo_atendimento` e `editar_bloco_exames` ainda carregam `font-family: 'Segoe UI', sans-serif;` – recomenda-se migrar para `--font-family-sans` para unificar.

## Escalas de espaçamento

| Token | Valor | Uso sugerido |
| --- | --- | --- |
| `--space-xxs` | `0.25rem` | Chips, espaçamento entre ícones e texto. |
| `--space-xs` | `0.5rem` | Padding interno de links na navbar. |
| `--space-sm` | `0.75rem` | Gaps menores em grids e cards. |
| `--space-md` | `1rem` | Padding padrão de botões e inputs. |
| `--space-lg` | `1.5rem` | Margens de seções e cards. |
| `--space-xl` | `2rem` | Respiro vertical em containers principais. |
| `padding-top: calc(var(--topbar-height) + env(safe-area-inset-top))` | `body` (`static/style.css`) | Garante compensação da navbar fixa em qualquer viewport. |

## Bordas e raios

| Token | Valor | Aplicação |
| --- | --- | --- |
| `--radius-sm` | `6px` | Controles de formulário (`.form-select`, `.quantity-selector`). |
| `--radius-md` | `8px` | Botões padrão, chips de filtro. |
| `--radius-lg` | `10px` | Cards, dropdowns, containers principais. |
| `border-radius: 1rem` | Cards em `base_consulta` | Em transição para `--radius-lg`; considerar refatoração futura. |
| `border-radius: 999px` | `.btn.rounded-pill`, `.schedule-toolbar-btn` | Call-to-actions de destaque. |

## Sombras

| Token | Valor | Contexto |
| --- | --- | --- |
| `--shadow-soft` | `0 4px 10px rgba(0, 0, 0, 0.05)` | Cards, dropdowns, alerts. |
| `--shadow-elevated` | `0 10px 25px rgba(0, 0, 0, 0.1)` | Hover de cards. |
| `--shadow-navbar` | `0 2px 10px rgba(0, 0, 0, 0.1)` | Navbar fixa. |
| `--shadow-navbar-strong` | `0 6px 15px rgba(0, 0, 0, 0.1)` | Hover dos botões `.btn`. |
| `.schedule-toolbar` | `0 18px 45px -35px rgba(79, 70, 229, 0.75)` | Destaque da toolbar de agenda. |
| `.schedule-action-btn` | `0 16px 32px -28px rgba(79, 70, 229, 0.2)` | Botões secundários na agenda. |
| `.btn-cart-floating` | `0 12px 26px rgba(0,0,0,.22)` | CTA flutuante da loja em mobile. |

## Componentes

### Botões

```css
.btn {
  border-radius: var(--radius-md);
  padding: var(--space-xs) var(--space-md);
  font-weight: var(--font-weight-medium);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.btn:hover { transform: translateY(-2px); box-shadow: var(--shadow-navbar-strong); }
.btn-primary { background-color: var(--color-primary); }
.btn-success { background-color: var(--color-secondary); }
.btn-danger { background-color: var(--color-danger); }
.btn-warning { background-color: var(--color-warning); color: #111; }
```

*Para CTAs redondos*, utilizar `.rounded-pill` ou as variantes da agenda (`.schedule-toolbar-btn`, `.schedule-action-btn`) para reforçar hierarquia.

### Cards

```css
.card {
  border: none;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.card:hover { box-shadow: var(--shadow-elevated); transform: translateY(-5px); }
.card-header { padding: var(--space-sm) var(--space-lg); font-weight: var(--font-weight-semibold); }
```

Cards em telas de consulta (herdadas de `base_consulta.html`) mantém `border-radius: 1rem` e sombra mais suave (`0 2px 10px rgba(0,0,0,0.05)`).

### Formulários

* **Layout padrão (`layout.html`):** Formularios utilizam `.form-label` com `fw-semibold` e `gap` via `.row.g-3` (`templates/agendamentos/appointments.html`).
* **Controles elevador:** grupos de busca (`templates/loja/loja.html`) aplicam classe utilitária `.input-elevated` com sombra média.
* **Auto-complete de exames:** `templates/orcamentos/editar_bloco_exames.html` adiciona `position-absolute` com `z-index:10` para listas de sugestão.

### Modais

```html
<div class="modal-content border-0 shadow-lg rounded-4 overflow-hidden">
  <div class="modal-header bg-primary text-white border-0">
    <h5 class="modal-title fw-semibold">Editar Horário do Colaborador</h5>
  </div>
  <div class="modal-body p-4">
    <!-- Conteúdo -->
  </div>
</div>
```

*Gradiente ou cor sólida devem respeitar a paleta; utilize `bg-primary` + texto branco ou declare tokens customizados.*

## Observações por tela

### `index`
- Os quatro cards principais usam `col-md-3`; em dispositivos ≤576px ficam empilhados, mas os botões não possuem largura total. Avaliar aplicar `w-100` para evitar cortes em textos longos.
- A classe personalizada `loja-pet-filled` mantém boa legibilidade, mas o texto `#d97706` sobre `#fff9db` atinge contraste ~3.4:1; considerar escurecer para ≥4.5:1 em links críticos.

### `appointments`
- O cabeçalho usa a classe `.text-gradient`, que ainda não possui definição CSS global. Adicionar regra (ex.: gradiente primário) para garantir consistência e acessibilidade.
- A `schedule-toolbar` oferece boa hierarquia, porém o gradiente `#0d6efd → #6610f2` destoa da cor institucional `#4e73df`. Recomenda-se alinhar os tons ou parametrizar via tokens.
- Em viewports <360px, a largura mínima (`padding: 1.5rem`) pode causar overflow horizontal; avaliar `padding-inline` responsivo.

### `loja`
- O `<style>` embutido redefine tokens (`--primary-color`) ao invés de herdar `--color-primary`. Migrar para variáveis globais evita divergências.
- No grid de filtros, os chips roláveis carecem de indicativo visual de overflow; adicionar `mask-image` ou `fade` lateral melhora a percepção.
- O botão flutuante mobile (`btn-cart-floating`) possui sombra intensa; verificar contraste do texto branco sobre gradiente verde (`btn-success`) em ambientes externos.

### `agendamentos/novo_atendimento`
- Herdando de `base_consulta.html`, mantém `font-family: 'Segoe UI'` e `btn-success` padrão Bootstrap (`#198754`), criando ruptura com a paleta nova. Recomenda-se migrar para `layout.html` ou reimportar `static/style.css`.
- As seções utilizam cards com `border-radius: 1rem`; alinhar para `--radius-lg` trará consistência com o restante do produto.

### `orcamentos/editar_bloco_exames`
- Inputs `textarea` extensos em cards empilhados podem gerar rolagem interna longa em mobile; considerar acordion ou tabs por exame para ergonomia.
- O botão `btn-danger btn-sm` tem contraste adequado, mas em modos de alto contraste o emoji `🗑️` pode desaparecer; sugerir suporte a `aria-label` ou ícone vetorial.
- Sugestões de auto-complete podem sobrepor cabeçalho fixo em telas pequenas; incluir `max-height` com rolagem própria.

---
Para evoluções, priorize migrar páginas legadas (`base_consulta.html`) para os tokens globais e formalize `.text-gradient` e variantes de gradiente como utilitárias centralizadas em `static/style.css`.
