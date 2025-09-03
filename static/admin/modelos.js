async function criarExameModelo(modalId){
  const nomeInput = document.getElementById(`${modalId}-nome`);
  const nome = nomeInput ? nomeInput.value.trim() : '';
  if(!nome){
    if(typeof mostrarFeedback === 'function') mostrarFeedback('Informe o nome do exame.', 'danger');
    return;
  }
  try{
    const resp = await fetch('/exame_modelo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ nome })
    });
    if(!resp.ok) throw new Error();
    const data = await resp.json();
    if(typeof mostrarFeedback === 'function') mostrarFeedback('Exame criado com sucesso!');
    closeModal(modalId);
    if(typeof inputExame !== 'undefined' && inputExame){
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      li.textContent = data.nome;
      li.onclick = () => {
        inputExame.value = data.nome;
        const just = document.getElementById('justificativa-exame');
        if(just) just.value = '';
        const sug = document.getElementById('sugestoes-exames');
        if(sug) sug.innerHTML = '';
      };
      const sugestoes = document.getElementById('sugestoes-exames');
      if(sugestoes){
        sugestoes.innerHTML='';
        sugestoes.appendChild(li);
      }
      li.click();
    }
  }catch(e){
    if(typeof mostrarFeedback === 'function') mostrarFeedback('Erro ao criar exame.', 'danger');
  }
}

async function salvarNovaMedicacao(modalId){
  const nomeEl = document.getElementById(`${modalId}-nome`);
  const principioEl = document.getElementById(`${modalId}-principio`);
  const nome = nomeEl ? nomeEl.value.trim() : '';
  const principio = principioEl ? principioEl.value.trim() : '';
  if(!nome || !principio){
    if(typeof mostrarFeedback === 'function') mostrarFeedback('Preencha nome e princípio ativo.', 'danger');
    return;
  }
  try{
    const res = await fetch('/medicamento_modelo', {
      method:'POST',
      headers:{ 'Content-Type':'application/json', 'Accept':'application/json' },
      body: JSON.stringify({ nome, principio_ativo: principio })
    });
    const data = await res.json();
    if(!res.ok || data.success === false) throw new Error(data.message || 'Erro ao salvar medicação');
    if(typeof mostrarFeedback === 'function') mostrarFeedback('Medicação cadastrada com sucesso!');
    closeModal(modalId);
    if(nomeEl) nomeEl.value='';
    if(principioEl) principioEl.value='';
    const input = document.getElementById('nome-medicamento');
    const sugestoes = document.getElementById('sugestoes-medicamentos');
    if(input && sugestoes){
      const li = document.createElement('li');
      li.className = 'list-group-item list-group-item-action';
      li.textContent = data.nome || nome;
      li.onclick = () => {
        if(typeof preencherCardMedicamento === 'function') preencherCardMedicamento(data);
        input.value = data.nome || nome;
        const dose = document.getElementById('dose');
        const freq = document.getElementById('frequencia');
        const duracao = document.getElementById('duracao');
        if(dose) dose.value = data.dosagem_recomendada || '';
        if(freq) freq.value = data.frequencia || '';
        if(duracao) duracao.value = data.duracao_tratamento || '';
        sugestoes.innerHTML='';
        sugestoes.style.display='none';
      };
      sugestoes.innerHTML='';
      sugestoes.appendChild(li);
      sugestoes.style.display='block';
      li.click();
    }
  }catch(err){
    if(typeof mostrarFeedback === 'function') mostrarFeedback('Erro ao salvar medicação.', 'danger');
  }
}
