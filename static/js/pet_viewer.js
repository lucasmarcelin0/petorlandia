/*
 * PetViewer — visualizadores em camada do prontuário.
 *
 *  - Foto do animal: abre ampliada a partir da miniatura (efeito "morph") e
 *    volta para ela ao fechar.
 *  - Documentos: PDF e imagens abrem num painel por cima da página, também
 *    expandindo a partir do cartão. PDF é desenhado com pdf.js (funciona no
 *    celular, onde o navegador não mostra PDF dentro de <iframe>).
 *
 * Tudo é melhoria progressiva: os links "Abrir" continuam com href/target
 * normais. Se este script ou o pdf.js falhar, o clique abre em nova aba como
 * antes. Respeita prefers-reduced-motion.
 */
(function () {
  'use strict';
  if (window.PetViewer) return;

  var OPEN_EASE = 'cubic-bezier(0.16, 1, 0.3, 1)';
  var CLOSE_EASE = 'cubic-bezier(0.65, 0, 0.35, 1)';
  var reduceQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

  function canAnimate() {
    return typeof Element !== 'undefined' && !!Element.prototype.animate &&
      !(reduceQuery && reduceQuery.matches);
  }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function noop() {}

  function config() {
    var el = document.getElementById('pet-viewer-config');
    return el ? el.dataset : {};
  }

  function make(tag, className, attrs) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (attrs) Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  // Promise que resolve quando a animação termina (ou foi cancelada).
  function finished(anim) {
    if (!anim) return Promise.resolve();
    if (anim.finished) return anim.finished.then(noop, noop);
    return new Promise(function (resolve) { anim.onfinish = anim.oncancel = resolve; });
  }

  // Transform que leva `el` (já na posição final) até o retângulo `from`.
  function morphTransform(el, from, uniform) {
    var to = el.getBoundingClientRect();
    if (!from || !to.width || !to.height) return null;
    var sx = from.width / to.width;
    var sy = uniform ? sx : from.height / to.height;
    sx = clamp(sx, 0.03, 3);
    sy = clamp(sy, 0.03, 3);
    var dx = (from.left + from.width / 2) - (to.left + to.width / 2);
    var dy = (from.top + from.height / 2) - (to.top + to.height / 2);
    return 'translate(' + dx.toFixed(1) + 'px,' + dy.toFixed(1) + 'px) scale(' + sx.toFixed(4) + ',' + sy.toFixed(4) + ')';
  }

  function isInViewport(rect) {
    return !!rect && rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 &&
      rect.top < window.innerHeight && rect.left < window.innerWidth;
  }

  function fade(el, from, to, duration, easing) {
    if (!canAnimate()) return Promise.resolve();
    return finished(el.animate([{ opacity: from }, { opacity: to }], {
      duration: duration, easing: easing || 'ease', fill: 'both'
    }));
  }

  // ---- Bloqueio de rolagem da página ----------------------------------
  var lockCount = 0;
  function lockScroll() {
    if (lockCount++ === 0) {
      document.documentElement.classList.add('pet-viewer-open');
      document.body.classList.add('pet-viewer-open');
    }
  }
  function unlockScroll() {
    if (lockCount > 0 && --lockCount === 0) {
      document.documentElement.classList.remove('pet-viewer-open');
      document.body.classList.remove('pet-viewer-open');
    }
  }

  // ---- Botão "voltar" do celular fecha a camada em vez de sair da tela ---
  var guards = [];
  function pushGuard(closeFn) {
    try { history.pushState({ petViewer: 1 }, ''); } catch (e) { return null; }
    var guard = { close: closeFn, active: true };
    guards.push(guard);
    return guard;
  }
  function releaseGuard(guard) {
    if (!guard || !guard.active) return;
    guard.active = false;
    var i = guards.indexOf(guard);
    if (i >= 0) guards.splice(i, 1);
    try { history.back(); } catch (e) { /* sem histórico: nada a desfazer */ }
  }
  window.addEventListener('popstate', function () {
    var guard = guards.pop();
    if (guard && guard.active) {
      guard.active = false;
      guard.close(true);
    }
  });

  // ---- Foco preso dentro da camada --------------------------------------
  function trapTab(container, e) {
    if (e.key !== 'Tab') return;
    var nodes = container.querySelectorAll(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    var focusable = Array.prototype.filter.call(nodes, function (n) { return n.offsetParent !== null; });
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  // =======================================================================
  // Foto do animal
  // =======================================================================
  var PHOTO_SELECTOR = [
    '.animal-photo img:not([data-photo-placeholder])',
    '#profile_photo-preview img',
    '#animal-image-preview img',
    '#profile_photo-img',
    '#animal-image-img'
  ].join(',');

  var photo = (function () {
    var overlay, backdrop, frame, img, caption, openLink, closeBtn;
    var source = null, isOpen = false, closing = false, guard = null, token = 0;

    function build() {
      if (overlay) return;
      overlay = make('div', 'photo-lightbox', {
        role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Visualização da foto'
      });
      backdrop = make('div', 'photo-lightbox__backdrop');
      frame = make('div', 'photo-lightbox__frame');
      img = make('img', 'photo-lightbox__img');
      img.id = 'image-overlay-img';
      frame.appendChild(img);
      caption = make('p', 'photo-lightbox__caption');
      var actions = make('div', 'photo-lightbox__actions');
      openLink = make('a', 'btn btn-light btn-sm', { target: '_blank', rel: 'noopener' });
      openLink.innerHTML = '<i class="fa-solid fa-up-right-from-square me-1" aria-hidden="true"></i>Abrir original';
      actions.appendChild(openLink);
      closeBtn = make('button', 'photo-lightbox__close', { type: 'button', 'aria-label': 'Fechar' });
      closeBtn.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';
      overlay.appendChild(backdrop);
      overlay.appendChild(closeBtn);
      overlay.appendChild(frame);
      overlay.appendChild(caption);
      overlay.appendChild(actions);
      document.body.appendChild(overlay);

      closeBtn.addEventListener('click', function () { close(); });
      backdrop.addEventListener('click', function () { close(); });
      overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
      overlay.addEventListener('keydown', function (e) { trapTab(overlay, e); });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && isOpen) { e.preventDefault(); close(); }
      });
    }

    function open(image) {
      var src = image.currentSrc || image.src;
      if (!src || isOpen) return;
      build();
      var myToken = ++token;
      source = image;
      var from = image.getBoundingClientRect();
      var label = (config().photoCaption || '').trim();
      img.src = src;
      img.alt = label ? 'Foto de ' + label : 'Foto';
      caption.textContent = label;
      caption.hidden = !label;
      var isData = src.indexOf('data:') === 0 || src.indexOf('blob:') === 0;
      openLink.hidden = isData;
      if (!isData) openLink.href = src;

      isOpen = true;
      closing = false;
      overlay.classList.add('is-open');
      frame.style.visibility = 'hidden';
      lockScroll();
      guard = pushGuard(function (fromPop) { close(fromPop); });

      var ready = img.decode ? img.decode().catch(noop) : Promise.resolve();
      ready.then(function () {
        if (myToken !== token || !isOpen) return;
        frame.style.visibility = '';
        if (!canAnimate()) return;
        fade(backdrop, 0, 1, 260);
        var start = morphTransform(frame, from, true);
        if (start) {
          frame.animate([
            { transform: start, opacity: 0.35 },
            { transform: 'none', opacity: 1 }
          ], { duration: 460, easing: OPEN_EASE });
        } else {
          frame.animate([{ opacity: 0, transform: 'scale(0.94)' }, { opacity: 1, transform: 'none' }],
            { duration: 280, easing: OPEN_EASE });
        }
        [caption, openLink.parentNode, closeBtn].forEach(function (el, i) {
          el.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
            { duration: 320, delay: 160 + i * 40, easing: 'ease-out', fill: 'backwards' });
        });
      });
      closeBtn.focus({ preventScroll: true });
    }

    function finish() {
      overlay.classList.remove('is-open');
      overlay.getAnimations && overlay.getAnimations({ subtree: true }).forEach(function (a) { a.cancel(); });
      img.removeAttribute('src');
      unlockScroll();
      isOpen = false;
      closing = false;
      source = null;
    }

    function close(fromPop) {
      if (!isOpen || closing) return;
      closing = true;
      if (!fromPop) releaseGuard(guard);
      guard = null;
      if (!canAnimate()) { finish(); return; }

      var target = source && document.contains(source) ? source.getBoundingClientRect() : null;
      var end = isInViewport(target) ? morphTransform(frame, target, true) : null;
      var tasks = [fade(backdrop, 1, 0, 280, CLOSE_EASE)];
      tasks.push(finished(frame.animate([
        { transform: 'none', opacity: 1 },
        end ? { transform: end, opacity: 0.2 } : { transform: 'translateY(24px) scale(0.96)', opacity: 0 }
      ], { duration: 340, easing: CLOSE_EASE, fill: 'forwards' })));
      [caption, openLink.parentNode, closeBtn].forEach(function (el) {
        el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in', fill: 'forwards' });
      });
      Promise.all(tasks).then(finish);
    }

    return { open: open, close: close };
  })();

  // =======================================================================
  // Documentos (PDF e imagens)
  // =======================================================================
  var pdfLibPromise = null;
  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    if (pdfLibPromise) return pdfLibPromise;
    var cfg = config();
    pdfLibPromise = new Promise(function (resolve, reject) {
      if (!cfg.pdfjs) { reject(new Error('pdf.js não configurado')); return; }
      var s = document.createElement('script');
      s.src = cfg.pdfjs;
      s.async = true;
      s.onload = function () {
        if (!window.pdfjsLib) { reject(new Error('pdf.js ausente')); return; }
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = cfg.pdfjsWorker;
        resolve(window.pdfjsLib);
      };
      s.onerror = function () { pdfLibPromise = null; reject(new Error('falha ao carregar pdf.js')); };
      document.head.appendChild(s);
    });
    return pdfLibPromise;
  }

  var docs = (function () {
    var overlay, backdrop, panel, titleEl, metaEl, iconEl, body, pagesEl, loader, loaderText,
      errorEl, errorText, imgEl, pageInd, zoomOutBtn, zoomInBtn, zoomLabel, newTabLink, waLink, closeBtn,
      toolsPdf;
    var isOpen = false, closing = false, guard = null, token = 0, trigger = null, fromRect = null;
    var pdf = null, pages = [], zoom = 1, observer = null, resizeTimer = null, scrollTick = false;

    var ICONS = { pdf: 'fa-file-pdf', image: 'fa-file-image' };

    function build() {
      if (overlay) return;
      overlay = make('div', 'doc-viewer');
      backdrop = make('div', 'doc-viewer__backdrop');
      panel = make('section', 'doc-viewer__panel', {
        role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'doc-viewer-title'
      });

      var bar = make('header', 'doc-viewer__bar');
      var head = make('div', 'doc-viewer__head');
      iconEl = make('span', 'doc-viewer__icon', { 'aria-hidden': 'true' });
      var titles = make('div', 'doc-viewer__titles');
      titleEl = make('strong', 'doc-viewer__title', { id: 'doc-viewer-title' });
      metaEl = make('small', 'doc-viewer__meta');
      titles.appendChild(titleEl);
      titles.appendChild(metaEl);
      head.appendChild(iconEl);
      head.appendChild(titles);

      var tools = make('div', 'doc-viewer__tools');
      toolsPdf = make('div', 'doc-viewer__zoom', { role: 'group', 'aria-label': 'Zoom' });
      zoomOutBtn = make('button', 'doc-viewer__btn', { type: 'button', 'aria-label': 'Diminuir zoom', title: 'Diminuir zoom' });
      zoomOutBtn.innerHTML = '<i class="fa-solid fa-magnifying-glass-minus" aria-hidden="true"></i>';
      zoomLabel = make('span', 'doc-viewer__zoom-label', { 'aria-live': 'polite' });
      zoomInBtn = make('button', 'doc-viewer__btn', { type: 'button', 'aria-label': 'Aumentar zoom', title: 'Aumentar zoom' });
      zoomInBtn.innerHTML = '<i class="fa-solid fa-magnifying-glass-plus" aria-hidden="true"></i>';
      toolsPdf.appendChild(zoomOutBtn);
      toolsPdf.appendChild(zoomLabel);
      toolsPdf.appendChild(zoomInBtn);
      newTabLink = make('a', 'doc-viewer__btn', { target: '_blank', rel: 'noopener', title: 'Abrir em nova aba', 'aria-label': 'Abrir em nova aba' });
      newTabLink.innerHTML = '<i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i>';
      waLink = make('a', 'doc-viewer__btn doc-viewer__btn--wa', { target: '_blank', rel: 'noopener', title: 'Enviar por WhatsApp', 'aria-label': 'Enviar por WhatsApp' });
      waLink.innerHTML = '<i class="fa-brands fa-whatsapp" aria-hidden="true"></i>';
      closeBtn = make('button', 'doc-viewer__btn doc-viewer__btn--close', { type: 'button', 'aria-label': 'Fechar', title: 'Fechar' });
      closeBtn.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';
      tools.appendChild(toolsPdf);
      tools.appendChild(newTabLink);
      tools.appendChild(waLink);
      tools.appendChild(closeBtn);
      bar.appendChild(head);
      bar.appendChild(tools);

      body = make('div', 'doc-viewer__body');
      pagesEl = make('div', 'doc-viewer__pages');
      imgEl = make('img', 'doc-viewer__img');
      imgEl.hidden = true;
      loader = make('div', 'doc-viewer__loader', { role: 'status' });
      loader.appendChild(make('span', 'doc-viewer__spinner', { 'aria-hidden': 'true' }));
      loaderText = make('span');
      loaderText.textContent = 'Carregando documento…';
      loader.appendChild(loaderText);
      errorEl = make('div', 'doc-viewer__error', { role: 'alert' });
      errorEl.hidden = true;
      errorEl.innerHTML = '<i class="fa-regular fa-circle-xmark" aria-hidden="true"></i>';
      errorText = make('p');
      errorEl.appendChild(errorText);
      var errorLink = make('a', 'btn btn-primary btn-sm', { target: '_blank', rel: 'noopener' });
      errorLink.textContent = 'Abrir em nova aba';
      errorLink.className = 'btn btn-primary btn-sm doc-viewer__error-link';
      errorEl.appendChild(errorLink);
      body.appendChild(pagesEl);
      body.appendChild(imgEl);
      body.appendChild(loader);
      body.appendChild(errorEl);

      pageInd = make('div', 'doc-viewer__pageind', { 'aria-live': 'polite' });
      pageInd.hidden = true;

      panel.appendChild(bar);
      panel.appendChild(body);
      panel.appendChild(pageInd);
      overlay.appendChild(backdrop);
      overlay.appendChild(panel);
      document.body.appendChild(overlay);

      closeBtn.addEventListener('click', function () { close(); });
      backdrop.addEventListener('click', function () { close(); });
      overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
      overlay.addEventListener('keydown', function (e) { trapTab(overlay, e); });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && isOpen) { e.preventDefault(); close(); }
      });
      zoomInBtn.addEventListener('click', function () { setZoom(zoom + 0.25); });
      zoomOutBtn.addEventListener('click', function () { setZoom(zoom - 0.25); });
      imgEl.addEventListener('click', function () { imgEl.classList.toggle('is-zoomed'); });
      body.addEventListener('scroll', function () {
        if (scrollTick) return;
        scrollTick = true;
        requestAnimationFrame(function () { scrollTick = false; updatePageIndicator(); });
      }, { passive: true });
      window.addEventListener('resize', function () {
        if (!isOpen || !pdf) return;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(layout, 160);
      });
    }

    // ---- PDF -------------------------------------------------------------
    function disposePdf() {
      if (observer) { observer.disconnect(); observer = null; }
      pages.forEach(function (p) { if (p.task) { try { p.task.cancel(); } catch (e) { /* já terminou */ } } });
      pages = [];
      if (pdf) { try { pdf.destroy(); } catch (e) { /* já destruído */ } pdf = null; }
      pagesEl.innerHTML = '';
    }

    function bodyInnerWidth() {
      var cs = window.getComputedStyle(pagesEl);
      var pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
      return Math.max(220, body.clientWidth - pad);
    }

    function layout() {
      if (!pdf || !pages.length) return;
      var ratio = body.scrollHeight ? body.scrollTop / body.scrollHeight : 0;
      var avail = bodyInnerWidth();
      pages.forEach(function (p) {
        if (p.task) { try { p.task.cancel(); } catch (e) { /* já terminou */ } p.task = null; }
        p.scale = (avail / p.vp.width) * zoom;
        p.wrap.style.width = Math.floor(p.vp.width * p.scale) + 'px';
        p.wrap.style.height = Math.floor(p.vp.height * p.scale) + 'px';
        p.wrap.classList.remove('is-rendered');
        p.wrap.innerHTML = '';
        p.rendered = false;
        p.rendering = false;
      });
      body.scrollTop = ratio * body.scrollHeight;
      zoomLabel.textContent = Math.round(zoom * 100) + '%';
      zoomOutBtn.disabled = zoom <= 0.5;
      zoomInBtn.disabled = zoom >= 3;
      observe();
      updatePageIndicator();
    }

    function observe() {
      if (observer) observer.disconnect();
      if (!('IntersectionObserver' in window)) {
        pages.forEach(renderPage);
        return;
      }
      observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) renderPage(entry.target.__page);
        });
      }, { root: body, rootMargin: '700px 0px' });
      pages.forEach(function (p) { observer.observe(p.wrap); });
    }

    function renderPage(p) {
      if (!p || p.rendered || p.rendering) return;
      p.rendering = true;
      var myToken = token;
      var viewport = p.page.getViewport({ scale: p.scale });
      var outputScale = Math.min(window.devicePixelRatio || 1, 2);
      var canvas = document.createElement('canvas');
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      var ctx = canvas.getContext('2d');
      p.task = p.page.render({
        canvasContext: ctx,
        viewport: viewport,
        transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null
      });
      p.task.promise.then(function () {
        if (myToken !== token || !pages.length) return;
        p.wrap.appendChild(canvas);
        p.wrap.classList.add('is-rendered');
        requestAnimationFrame(function () { canvas.classList.add('is-ready'); });
        p.rendered = true;
        p.rendering = false;
        p.task = null;
      }).catch(function (err) {
        p.rendering = false;
        p.task = null;
        if (err && err.name === 'RenderingCancelledException') return;
        if (window.console) console.warn('Falha ao desenhar página do PDF', err);
      });
    }

    function setZoom(value) {
      var next = clamp(Math.round(value * 4) / 4, 0.5, 3);
      if (next === zoom) return;
      zoom = next;
      layout();
    }

    function updatePageIndicator() {
      if (!pages.length) return;
      var top = body.getBoundingClientRect().top;
      var current = 1;
      for (var i = 0; i < pages.length; i++) {
        var r = pages[i].wrap.getBoundingClientRect();
        if (r.bottom - top > body.clientHeight * 0.35) { current = i + 1; break; }
        current = i + 1;
      }
      pageInd.textContent = current + ' / ' + pages.length;
      pageInd.hidden = pages.length < 2;
    }

    function openPdf(src, myToken) {
      return loadPdfJs().then(function (lib) {
        return lib.getDocument({ url: src, withCredentials: true }).promise;
      }).then(function (doc) {
        if (myToken !== token || !isOpen) { doc.destroy(); return; }
        pdf = doc;
        var tasks = [];
        for (var n = 1; n <= doc.numPages; n++) { tasks.push(doc.getPage(n)); }
        return Promise.all(tasks);
      }).then(function (list) {
        if (!list || myToken !== token || !isOpen) return;
        list.forEach(function (page, idx) {
          var wrap = make('div', 'doc-viewer__page');
          wrap.style.setProperty('--i', Math.min(idx, 6));
          var p = { page: page, wrap: wrap, vp: page.getViewport({ scale: 1 }), rendered: false, rendering: false, task: null, scale: 1 };
          wrap.__page = p;
          pages.push(p);
          pagesEl.appendChild(wrap);
        });
        loader.hidden = true;
        layout();
      });
    }

    function showError(message) {
      loader.hidden = true;
      errorText.textContent = message;
      errorEl.hidden = false;
    }

    // ---- Abrir / fechar ----------------------------------------------------
    function open(link) {
      if (isOpen) return;
      build();
      var d = link.dataset;
      var kind = d.docKind === 'image' ? 'image' : 'pdf';
      var myToken = ++token;
      trigger = link;
      var card = link.closest('.doc-card') || link;
      fromRect = card.getBoundingClientRect();

      titleEl.textContent = d.docName || 'Documento';
      metaEl.textContent = d.docMeta || '';
      metaEl.hidden = !d.docMeta;
      iconEl.className = 'doc-viewer__icon doc-viewer__icon--' + kind;
      iconEl.innerHTML = '<i class="fa-solid ' + ICONS[kind] + '"></i>';
      newTabLink.href = d.docOpen || link.href;
      var wa = card.querySelector('.js-doc-whatsapp');
      waLink.hidden = !wa;
      if (wa) waLink.href = wa.href;
      toolsPdf.hidden = kind !== 'pdf';
      overlay.querySelector('.doc-viewer__error-link').href = d.docOpen || link.href;

      zoom = 1;
      disposePdf();
      imgEl.hidden = true;
      imgEl.classList.remove('is-zoomed');
      imgEl.removeAttribute('src');
      errorEl.hidden = true;
      loader.hidden = false;
      loaderText.textContent = kind === 'pdf' ? 'Carregando PDF…' : 'Carregando imagem…';
      pageInd.hidden = true;
      body.scrollTop = 0;

      isOpen = true;
      closing = false;
      overlay.classList.add('is-open');
      lockScroll();
      guard = pushGuard(function (fromPop) { close(fromPop); });

      if (canAnimate()) {
        fade(backdrop, 0, 1, 280);
        var start = morphTransform(panel, fromRect, false);
        var anim = panel.animate(start ? [
          { transform: start, opacity: 0.4, borderRadius: '1rem' },
          { transform: 'none', opacity: 1, borderRadius: getComputedStyle(panel).borderRadius }
        ] : [
          { transform: 'translateY(28px) scale(0.96)', opacity: 0 },
          { transform: 'none', opacity: 1 }
        ], { duration: 520, easing: OPEN_EASE });
        void anim;
        [].slice.call(panel.children).forEach(function (child, i) {
          child.animate([{ opacity: 0 }, { opacity: 1 }],
            { duration: 280, delay: 140 + i * 50, easing: 'ease-out', fill: 'backwards' });
        });
      }
      closeBtn.focus({ preventScroll: true });

      if (kind === 'image') {
        imgEl.onload = function () {
          if (myToken !== token) return;
          loader.hidden = true;
          imgEl.hidden = false;
        };
        imgEl.onerror = function () { if (myToken === token) showError('Não foi possível carregar a imagem.'); };
        imgEl.alt = d.docName || 'Imagem do documento';
        imgEl.src = d.docSrc;
      } else {
        openPdf(d.docSrc, myToken).catch(function (err) {
          if (myToken !== token || !isOpen) return;
          if (window.console) console.warn('Falha ao abrir PDF', err);
          showError('Não foi possível exibir este PDF aqui.');
        });
      }
    }

    function finish() {
      overlay.classList.remove('is-open');
      overlay.getAnimations && overlay.getAnimations({ subtree: true }).forEach(function (a) { a.cancel(); });
      disposePdf();
      imgEl.removeAttribute('src');
      unlockScroll();
      isOpen = false;
      closing = false;
      token++;
      var back = trigger;
      trigger = null;
      if (back && document.contains(back)) back.focus({ preventScroll: true });
    }

    function close(fromPop) {
      if (!isOpen || closing) return;
      closing = true;
      if (!fromPop) releaseGuard(guard);
      guard = null;
      if (!canAnimate()) { finish(); return; }

      var card = trigger && (trigger.closest('.doc-card') || trigger);
      var target = card && document.contains(card) ? card.getBoundingClientRect() : null;
      var end = isInViewport(target) ? morphTransform(panel, target, false) : null;
      var tasks = [fade(backdrop, 1, 0, 300, CLOSE_EASE)];
      tasks.push(finished(panel.animate([
        { transform: 'none', opacity: 1 },
        end ? { transform: end, opacity: 0.3 } : { transform: 'translateY(32px) scale(0.96)', opacity: 0 }
      ], { duration: 380, easing: CLOSE_EASE, fill: 'forwards' })));
      Promise.all(tasks).then(finish);
    }

    return { open: open, close: close };
  })();

  // ---- Ligação aos elementos da página (delegação de eventos) --------------
  function plainClick(e) {
    return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || !plainClick(e)) return;

    var docLink = e.target.closest && e.target.closest('a[data-doc-viewer]');
    if (docLink) {
      e.preventDefault();
      docs.open(docLink);
      return;
    }

    var image = e.target.closest && e.target.closest(PHOTO_SELECTOR);
    if (image && image.tagName === 'IMG') {
      photo.open(image);
    }
  });

  window.PetViewer = { photo: photo, docs: docs };
})();
