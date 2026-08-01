(() => {
  const form = document.getElementById('subscription-form');
  if (!form) return;
  const variant = document.getElementById('variant_id');
  const single = document.getElementById('single-price');
  const quantity = document.getElementById('quantidade');
  const frequency = document.getElementById('frequencia_dias');
  const shipping = Number(form.dataset.shipping || 0);
  const money = value => value.toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
  });
  const labels = {
    '15': 'a cada 15 dias',
    '30': 'todo mês',
    '60': 'a cada 2 meses',
    '90': 'a cada 3 meses',
  };

  function updateSummary() {
    const selected = variant ? variant.options[variant.selectedIndex] : single;
    const unit = Number(selected?.dataset.price || 0);
    const subtotal = unit * Number(quantity.value || 1);
    document.getElementById('summary-subtotal').textContent = money(subtotal);
    document.getElementById('summary-total').textContent = money(subtotal + shipping);
    document.getElementById('summary-frequency').textContent = labels[frequency.value] || '';
  }

  [variant, quantity, frequency]
    .filter(Boolean)
    .forEach(element => element.addEventListener('change', updateSummary));
  updateSummary();
})();
