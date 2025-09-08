document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-mask]').forEach(el => {
    const mask = el.dataset.mask;
    if (mask) {
      Inputmask({ mask }).mask(el);
    }
  });
});
