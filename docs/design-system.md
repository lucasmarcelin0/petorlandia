# Propostas de Sistema Visual

Este documento consolida sugestões de cores, tipografia, escalas de espaçamento/raio/sombra e diretrizes de ícones alinhadas ao visual atual do PetOrlândia.

## 1. Paletas cromáticas com contraste AA

As variações abaixo foram calculadas garantindo contraste mínimo **AA (≥ 4,5:1)** para texto normal sobre os fundos sugeridos. As cores partem dos azuis, verdes e amarelos já presentes no layout base (`#4e73df`, `#1cc88a`, `#f6c23e`).

### a. Atlântico (vibração fria)
| Token | Hex | Uso sugerido | Contraste (fundo → texto) |
| --- | --- | --- | --- |
| `--color-primary` | `#3652A3` | Botões principais, links, destaques | `#3652A3` com texto `#FFFFFF` = 7,26:1 |
| `--color-secondary` | `#1F7A8C` | Chips informativos, botões secundários | `#1F7A8C` com texto `#FFFFFF` = 4,98:1 |
| `--color-neutral-surface` | `#F1F5F9` | Fundos de cards, páginas | `#1F2933` sobre `#F1F5F9` = 13,47:1 |
| `--color-alert` | `#B91C1C` | Erros, estados críticos | `#FFFFFF` sobre `#B91C1C` = 6,47:1 |

### b. Jardim (terra + folhagem)
| Token | Hex | Uso sugerido | Contraste |
| --- | --- | --- | --- |
| `--color-primary` | `#2D6A4F` | Ações afirmativas, links | `#2D6A4F` com texto `#FFFFFF` = 6,39:1 |
| `--color-secondary` | `#F4A259` | Estados neutro-positivos, badges | `#1F2933` sobre `#F4A259` = 7,14:1 |
| `--color-neutral-surface` | `#F6F1ED` | Painéis suaves, listas | `#2D4059` sobre `#F6F1ED` = 9,41:1 |
| `--color-alert` | `#DC2626` | Alertas imediatos | `#FFFFFF` sobre `#DC2626` = 4,83:1 |

### c. Crepúsculo (pôr do sol digital)
| Token | Hex | Uso sugerido | Contraste |
| --- | --- | --- | --- |
| `--color-primary` | `#7C3AED` | Call-to-action, gráficos | `#7C3AED` com texto `#FFFFFF` = 5,70:1 |
| `--color-secondary` | `#38BDF8` | Estados informativos, tooltips | `#0F172A` sobre `#38BDF8` = 8,64:1 |
| `--color-neutral-surface` | `#EEF2F6` | Fundos claros gerais | `#1F2933` sobre `#EEF2F6` = 12,54:1 |
| `--color-alert` | `#CC3A30` | Alertas quentes | `#FFFFFF` sobre `#CC3A30` = 4,98:1 |

> **Notas de implementação**
> * Para estados `hover`/`focus`, escureça ou clareie os tons em ~8% mantendo contraste ≥ 4,5:1.
> * Ícones sobre botões devem seguir a mesma cor do texto para garantir consistência.

## 2. Tipografia recomendada

| Contexto | Família Google Fonts | Pesos sugeridos | Fallback seguro |
| --- | --- | --- | --- |
| Títulos & CTA | [Manrope](https://fonts.google.com/specimen/Manrope) | 500, 600, 700 | `"Manrope", "Poppins", system-ui, sans-serif` |
| Corpo de texto | [Inter](https://fonts.google.com/specimen/Inter) | 400, 500 | `"Inter", "Poppins", "Helvetica Neue", Arial, sans-serif` |
| Ênfases/pequenos destaques | [Poppins](https://fonts.google.com/specimen/Poppins) (já carregada) | 500, 600 | `"Poppins", "Segoe UI", sans-serif` |

Recomendações:

* Definir `font-display: swap` na importação para evitar FOUT.
* Alturas de linha: 1,3 em títulos, 1,55 em corpo de texto, 1,4 em labels/inputs.
* Escala de tamanhos (rem): 0,75 – 0,875 – 1 – 1,125 – 1,5 – 1,875 para hierarquizar headings e textos auxiliares.

## 3. Escalas de espaçamento, bordas e sombras

### Espaçamento (`--space-*`)
`0.25rem (4px)`, `0.5rem (8px)`, `0.75rem (12px)`, `1rem (16px)`, `1.5rem (24px)`, `2rem (32px)`, `3rem (48px)`.

* Botões: `padding-inline` `0.75rem`, `padding-block` `0.5rem`.
* Cards: `padding` `1.5rem` com `gap` interno `1rem` entre elementos.
* Inputs e selects: `padding` `0.5rem` vertical × `0.75rem` horizontal.

### Raios de borda (`--radius-*`)
`0.25rem (4px)`, `0.5rem (8px)`, `1rem (16px)`, `999px` (para chips/píbulas).

* Botões primários/secundários: `0.5rem`.
* Cards e modais: `1rem`.
* Inputs: `0.5rem`; pill buttons/chips: `999px`.

### Sombras (`--shadow-*`)
* `--shadow-sm`: `0 1px 2px rgba(15, 23, 42, 0.12)` – inputs elevados.
* `--shadow-md`: `0 6px 16px rgba(15, 23, 42, 0.16)` – cards, dropdowns.
* `--shadow-lg`: `0 18px 45px rgba(79, 70, 229, 0.25)` – banners, hero cards (inspirado na barra de agenda atual).

## 4. Ícones e ilustrações

* **Bibliotecas suportadas:**
  * [Font Awesome 6](https://fontawesome.com/) – já referenciada no layout base para ícones gerais.
  * [Bootstrap Icons](https://icons.getbootstrap.com/) – mantém coerência com componentes Bootstrap existentes.
* **Tamanhos padrão:** `1rem` para texto inline, `1.25rem` em botões médios, `1.5rem–2rem` em cards hero. Para ícones independentes, utilize múltiplos da escala de espaçamento.
* **Cores:** seguir o token do texto adjacente (ex.: `currentColor`). Em áreas coloridas, assegurar contraste ≥ 4,5:1 entre ícone e fundo.
* **Ilustrações & Lottie:**
  * Utilizar até 30% da largura do container em telas ≥ 992px, 50% em mobile.
  * Priorizar ilustrações com outlines suaves e paleta derivada das variações acima.
  * Para animações Lottie, limitar duração entre 2–4s com `loop` apenas quando o movimento auxiliar o entendimento. Pausar automaticamente quando fora do viewport.

---

Estas diretrizes permitem evoluir o design mantendo coerência com o tema atual enquanto ampliam possibilidades de personalização.
