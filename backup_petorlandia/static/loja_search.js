// Filtro de produtos em tempo real na loja
 document.addEventListener('DOMContentLoaded', () => {
   const input = document.querySelector('.js-search-input');
   const container = document.querySelector('.js-products-container');
   if (!input || !container) return;
   const items = container.querySelectorAll('.col');
   input.addEventListener('input', () => {
     const term = input.value.toLowerCase();
     items.forEach(item => {
       const name = item.querySelector('.product-name').textContent.toLowerCase();
       const desc = item.querySelector('.product-description').textContent.toLowerCase();
       if (name.includes(term) || desc.includes(term)) {
         item.classList.remove('d-none');
       } else {
         item.classList.add('d-none');
       }
     });
   });
 });
