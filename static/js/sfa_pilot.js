(function () {
  'use strict';
  const list = document.getElementById('workplaces');
  if (list) {
    const template = list.firstElementChild.cloneNode(true);
    const renumber = () => list.querySelectorAll('.work-index').forEach((span, i) => { span.textContent = i + 1; });
    document.getElementById('add-work').addEventListener('click', () => {
      if (list.children.length >= 20) return;
      const item = template.cloneNode(true);
      item.querySelectorAll('input,select').forEach(control => { control.value = ''; });
      list.appendChild(item); renumber(); item.querySelector('select').focus();
    });
    list.addEventListener('click', event => {
      if (!event.target.classList.contains('remove-work')) return;
      event.target.closest('.workplace').remove(); renumber();
    });
  }
  const onset = document.getElementById('answer__data_inicio_sintomas');
  const status = document.getElementById('pilot-calendar');
  function calendar() {
    if (!onset) return;
    if (!onset.value) { status.textContent = 'Se deixar o início em branco, será mantida a data informada no cadastro, quando houver.'; return; }
    const parts = onset.value.split('-').map(Number);
    const start = new Date(Date.UTC(parts[0], parts[1]-1, parts[2]));
    const format = days => new Date(start.getTime()+days*86400000).toLocaleDateString('pt-BR', {timeZone:'UTC'});
    status.textContent = 'Referências: T7 em '+format(7)+'; T30 em '+format(30)+'. T0 continua sendo a data real do primeiro preenchimento.';
  }
  if (onset) onset.addEventListener('input', calendar);
  calendar();
})();
