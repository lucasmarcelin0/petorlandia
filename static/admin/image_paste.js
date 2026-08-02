(function () {
  'use strict';

  const INPUT_SELECTOR = 'input[type="file"][data-image-paste="true"]';
  const DEFAULT_MAX_BYTES = 20 * 1024 * 1024;
  const MIME_EXTENSIONS = Object.freeze({
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/bmp': 'bmp'
  });
  const decoratedInputs = new WeakMap();
  let activeInput = null;

  function formatBytes(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`;
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text) element.textContent = text;
    return element;
  }

  function setActive(input) {
    if (activeInput && decoratedInputs.has(activeInput)) {
      decoratedInputs.get(activeInput).zone.classList.remove('is-active');
    }
    activeInput = input;
    decoratedInputs.get(input)?.zone.classList.add('is-active');
  }

  function setStatus(input, message, tone) {
    const elements = decoratedInputs.get(input);
    if (!elements) return;
    elements.zone.classList.remove('is-success', 'is-error');
    if (tone) elements.zone.classList.add(`is-${tone}`);
    elements.status.textContent = message;
  }

  function showPreview(input, file) {
    const elements = decoratedInputs.get(input);
    if (!elements) return;
    setStatus(input, `${file.name} · ${formatBytes(file.size)}`, 'success');
    const reader = new FileReader();
    reader.addEventListener('load', () => {
      elements.preview.replaceChildren();
      const image = createElement('img');
      image.src = reader.result;
      image.alt = 'Pré-visualização da imagem selecionada';
      elements.preview.appendChild(image);
    });
    reader.addEventListener('error', () => {
      setStatus(input, 'A imagem foi anexada, mas a pré-visualização não pôde ser exibida.', 'error');
    });
    reader.readAsDataURL(file);
  }

  function validateFile(input, file) {
    if (!file || !MIME_EXTENSIONS[file.type]) {
      setStatus(input, 'Formato não aceito. Use JPG, PNG, GIF, WebP ou BMP.', 'error');
      return false;
    }
    const maxBytes = Number(input.dataset.maxBytes) || DEFAULT_MAX_BYTES;
    if (file.size > maxBytes) {
      setStatus(input, `A imagem excede o limite de ${formatBytes(maxBytes)}.`, 'error');
      return false;
    }
    return true;
  }

  function normalizedClipboardFile(file) {
    const extension = MIME_EXTENSIONS[file.type];
    if (!extension) return file;
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '').replace('T', '-');
    return new File([file], `imagem-colada-${stamp}.${extension}`, {
      type: file.type,
      lastModified: Date.now()
    });
  }

  function applyFile(input, file, fromClipboard) {
    const candidate = fromClipboard ? normalizedClipboardFile(file) : file;
    if (!validateFile(input, candidate)) return false;
    if (fromClipboard) {
      const transfer = new DataTransfer();
      transfer.items.add(candidate);
      decoratedInputs.get(input).transfer = transfer;
      input.files = transfer.files;
    }
    showPreview(input, candidate);
    input.dataset.imagePasteDispatch = 'true';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    delete input.dataset.imagePasteDispatch;
    return true;
  }

  function decorateInput(input) {
    if (decoratedInputs.has(input)) return;
    input.accept = 'image/jpeg,image/png,image/gif,image/webp,image/bmp';

    const zone = createElement('div', 'admin-image-paste-zone');
    zone.tabIndex = 0;
    zone.setAttribute('role', 'region');
    zone.setAttribute('aria-label', `Colar imagem em ${input.name || 'campo de imagem'}`);

    const preview = createElement('span', 'admin-image-paste-preview');
    const icon = createElement('i', 'fa-solid fa-image');
    icon.setAttribute('aria-hidden', 'true');
    preview.appendChild(icon);

    const copy = createElement('span', 'admin-image-paste-copy');
    copy.appendChild(createElement('strong', '', 'Cole uma imagem diretamente neste campo'));
    const hint = createElement('span');
    hint.append('Pressione ');
    hint.appendChild(createElement('kbd', 'admin-image-paste-key', 'Ctrl'));
    hint.append(' + ');
    hint.appendChild(createElement('kbd', 'admin-image-paste-key', 'V'));
    hint.append(' ou use “Escolher arquivo” acima.');
    copy.appendChild(hint);
    const status = createElement('span', 'admin-image-paste-status', 'JPG, PNG, GIF, WebP ou BMP · até 20 MB');
    status.setAttribute('aria-live', 'polite');
    copy.appendChild(status);

    zone.append(preview, copy);
    input.insertAdjacentElement('afterend', zone);
    decoratedInputs.set(input, { zone, preview, status, transfer: null });

    input.addEventListener('focus', () => setActive(input));
    input.addEventListener('click', () => setActive(input));
    input.addEventListener('change', () => {
      if (input.dataset.imagePasteDispatch === 'true') return;
      const file = input.files?.[0];
      if (file && validateFile(input, file)) showPreview(input, file);
    });
    zone.addEventListener('pointerdown', () => setActive(input));
    zone.addEventListener('focus', () => setActive(input));
    zone.addEventListener('click', () => {
      setActive(input);
      zone.focus({ preventScroll: true });
    });
  }

  function visibleInputs() {
    return Array.from(document.querySelectorAll(INPUT_SELECTOR)).filter(input => {
      return !input.disabled && input.getClientRects().length > 0;
    });
  }

  function clipboardImage(event) {
    const items = Array.from(event.clipboardData?.items || []);
    const item = items.find(candidate => candidate.kind === 'file' && candidate.type.startsWith('image/'));
    if (item) return item.getAsFile();
    return Array.from(event.clipboardData?.files || []).find(file => file.type.startsWith('image/')) || null;
  }

  function targetForPaste(event, inputs) {
    const eventElement = event.target instanceof Element ? event.target : null;
    const zone = eventElement?.closest('.admin-image-paste-zone');
    if (zone) return inputs.find(input => decoratedInputs.get(input)?.zone === zone) || null;
    if (activeInput && inputs.includes(activeInput)) return activeInput;
    if (inputs.length === 1) return inputs[0];
    return null;
  }

  function handlePaste(event) {
    if (event.__photoCropperHandled || event.__adminImagePasteHandled) return;
    const eventElement = event.target instanceof Element ? event.target : null;
    if (eventElement?.closest('input:not([type="file"]), textarea, [contenteditable="true"]')) return;
    const file = clipboardImage(event);
    if (!file) return;
    const inputs = visibleInputs();
    if (!inputs.length) return;
    const target = targetForPaste(event, inputs);
    if (!target) {
      inputs.forEach(input => setStatus(input, 'Clique no campo desejado e pressione Ctrl+V novamente.', 'error'));
      event.preventDefault();
      return;
    }
    setActive(target);
    if (applyFile(target, file, true)) {
      event.__adminImagePasteHandled = true;
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function initAll(root) {
    if (root.matches?.(INPUT_SELECTOR)) decorateInput(root);
    root.querySelectorAll?.(INPUT_SELECTOR).forEach(decorateInput);
  }

  document.addEventListener('DOMContentLoaded', () => {
    initAll(document);
    document.addEventListener('paste', handlePaste);
    const observer = new MutationObserver(mutations => {
      mutations.forEach(mutation => mutation.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) initAll(node);
      }));
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });

  window.AdminImagePaste = Object.freeze({ initAll, applyFile });
}());
