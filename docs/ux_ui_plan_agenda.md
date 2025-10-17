# Plano de melhorias de UX/UI para a agenda do veterinário

Este documento consolida propostas para tornar a interface da página de agendamentos mais elegante, sofisticada e funcional quando acessada como veterinário.

## Aba "Calendário"
- **Visão de densidade ajustável**: permitir alternar entre modos compacto e confortável, reduzindo alturas de linha em telas grandes para aumentar o número de horários visíveis sem perder legibilidade.
- **Paleta refinada e temática**: aplicar tons pastel inspirados na identidade visual da clínica, com contrastes suaves e ícones minimalistas, mantendo indicadores de status com bordas finas e micro animações de destaque ao passar o cursor.
- **Indicadores de prioridade e tags**: adicionar rótulos coloridos discretos (ex.: emergência, retorno, primeira consulta) diretamente nos cards dos eventos, melhorando a percepção rápida do contexto.
- **Linha do tempo vertical responsiva**: alinhar os cartões de consulta a uma régua temporal com divisórias semitransparentes e marcadores de hora para facilitar a leitura rápida do dia.
- **Feedback contextual em hover**: mostrar tooltips ricos com resumo do paciente, tutor e última evolução ao posicionar o cursor sobre o evento, diminuindo cliques desnecessários.

## Aba "Agendamento"
- **Formulário em etapas suaves**: converter o formulário linear em um fluxo por etapas (tutor → paciente → data/horário → detalhes), com breadcrumbs animados para guiar o usuário.
- **Componentes com preenchimento automático inteligente**: sugerir automaticamente o tutor ao selecionar o pet, exibindo chips confirmando a relação e evitando erros.
- **Calendário lateral integrado**: incorporar um mini calendário inline sincronizado com a seleção de data para visualizar disponibilidade sem sair da aba.
- **Mensagens de validação proativas**: mostrar orientações e limites antes de erros (ex.: tempo mínimo entre consultas), utilizando micro textos assistivos abaixo dos campos.
- **Botões principais com hierarquia clara**: aplicar estilo primário consistente (gradiente sutil, bordas arredondadas menores) para ações positivas e secundário outline para ações neutras, reforçando acessibilidade com labels e ícones.

## Painel de resumo lateral
- **Cards com estados visuais distintos**: reorganizar o painel com cartões compactos que agrupem indicadores por profissional, usando barras de progresso e micro gráficos para facilitar comparações.
- **Alertas priorizados**: destacar retornos pendentes ou slots críticos com badges em vermelho queimado e, opcionalmente, vibração suave ao abrir a página.
- **Acesso rápido a filtros**: incluir switches ou chips interativos que apliquem filtros instantâneos (ex.: somente emergências) refletindo-se tanto no calendário quanto na lista.

## Considerações gerais
- **Tipografia harmonizada**: utilizar uma combinação de títulos em peso semi-bold e corpo em regular com espaçamento generoso, garantindo contraste mínimo AA.
- **Animações sutis**: aplicar transições de 150–200ms em abas, colapsáveis e tooltips para sensação de fluidez.
- **Modo escuro opcional**: preparar tokens de cores e variáveis CSS para oferecer modo escuro sem perda de contraste nos estados de status.
