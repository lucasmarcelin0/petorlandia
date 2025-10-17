# Inventário visual - componentes críticos

## Botões
- **CTAs principais (Home autenticada)**  
  - Local: `templates/index.html`, cards de boas-vindas (`.btn btn-outline-*` e `.rounded-pill`).  
  - Estilos-chave: uso de `btn-outline-success`, `btn-outline-primary`, `btn-outline-info`, `btn-outline-warning` com sombras inline (`shadow-sm`) e `border-radius: 999px`.  
  - Captura sugerida: agrupar quatro CTAs com animações Lottie para evidenciar uso de outline + pills.
- **Botão "Início" (Consultas)**  
  - Local: `templates/base_consulta.html` (`.btn-back`).  
  - Estilos-chave: cor `#0d6efd`, tipografia `font-weight: 500`, ícone `bi-arrow-left-circle`.  
  - Captura sugerida: topo da página de consulta mostrando contraste com gradiente `#e3f2fd → #ffffff`.
- **Toolbar da agenda**  
  - Local: `static/styles.css` (`.schedule-toolbar` e variantes `--info`, `--success`, `--warning`, `--primary`).  
  - Estilos-chave: gradientes vivos (ex.: `#0d6efd → #6610f2`) e sombras profundas.  
  - Captura sugerida: vista da barra com botões tipo chip para demonstrar discrepância cromática.

## Cards
- **Card de boas-vindas (visitante)**  
  - Local: `templates/index.html`, card com `background: white` e `shadow-lg`.  
  - Estilos-chave: `border-radius: 1rem`, integração com `logo-img` (ver `static/images.css`).  
  - Captura sugerida: card completo com call-to-action "Criar Conta" / "Entrar".
- **Cards área profissional/entregas**  
  - Local: `templates/index.html`, cards `shadow-lg` com `background: #ffffff`.  
  - Estilos-chave: uso repetido de pills e ícones emoji para identificar seções.  
  - Captura sugerida: seção expandida para validar espaçamento entre botões (`gap: 3`).
- **Cards de consulta**  
  - Local: `templates/base_consulta.html` (`.card`).  
  - Estilos-chave: `border-radius: 1rem`, `box-shadow: 0 2px 10px rgba(0,0,0,0.05)`.  
  - Captura sugerida: modal ou card principal exibindo campos de formulário.

## Formulários
- **Formulários de consulta**  
  - Local: herdam de `templates/base_consulta.html`; inputs `form-control`, `flatpickr`, `Inputmask`.  
  - Estilos-chave: hover `box-shadow: 0 6px 15px rgba(0,0,0,0.1)` em `.btn`, modais com `max-height: 70-90vh`.  
  - Captura sugerida: modal aberto destacando scroll interno (`.modal-body`).
- **Campos Data + Idade**  
  - Local: `static/styles.css` (`.data-idade`).  
  - Estilos-chave: `font-weight: 600`, `min-width` para inputs/seletores, comportamento responsivo para <576px.  
  - Captura sugerida: formulário onde o componente aparece com labels para discutir largura mínima.

## Observações de conflito visual
- Tipografia: `Poppins` (layout principal) vs. `Segoe UI` (base de consulta) – unificar para evitar salto visual.  
- Paleta: `#4e73df` (tema global) vs. `#0d6efd` (Bootstrap) vs. gradientes da agenda (`#7c3aed`, `#2563eb`) – mapear tokens para identificar qual prevalece.  
- Sombras: navbar (`0 2px 10px rgba(0,0,0,0.1)`) vs. hover botões (`0 6px 15px rgba(0,0,0,0.1)`) vs. toolbar agenda (`0 18px 45px -35px rgba(79,70,229,0.75)`) – alinhar intensidade.
