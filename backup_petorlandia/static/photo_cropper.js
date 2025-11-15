function initPhotoCropper(prefix) {
  const img = document.getElementById(prefix + '-img');
  const fileInput = document.getElementById(prefix);
  const rotField = document.getElementById(prefix + '-rotation');
  const zoomField = document.getElementById(prefix + '-zoom');
  const offsetXField = document.getElementById(prefix + '-offset-x');
  const offsetYField = document.getElementById(prefix + '-offset-y');
  const rotateLeft = document.getElementById(prefix + '-rotate-left');
  const rotateRight = document.getElementById(prefix + '-rotate-right');
  const zoomIn = document.getElementById(prefix + '-zoom-in');
  const zoomOut = document.getElementById(prefix + '-zoom-out');

  let rotation = rotField ? parseInt(rotField.value || 0, 10) : 0;
  let zoom = zoomField ? parseFloat(zoomField.value || 1) : 1;
  let offsetX = offsetXField ? parseFloat(offsetXField.value || 0) : 0;
  let offsetY = offsetYField ? parseFloat(offsetYField.value || 0) : 0;

  function update() {
    if (img) {
      img.style.transform = `translate(${offsetX}px, ${offsetY}px) rotate(${rotation}deg) scale(${zoom})`;
    }
    if (rotField) rotField.value = rotation;
    if (zoomField) zoomField.value = zoom.toFixed(2);
    if (offsetXField) offsetXField.value = Math.round(offsetX);
    if (offsetYField) offsetYField.value = Math.round(offsetY);
  }

  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = ev => { if (img) img.src = ev.target.result; };
        reader.readAsDataURL(file);
      }
    });
  }

  if (rotateLeft) rotateLeft.addEventListener('click', () => { rotation = (rotation - 90 + 360) % 360; update(); });
  if (rotateRight) rotateRight.addEventListener('click', () => { rotation = (rotation + 90) % 360; update(); });
  if (zoomIn) zoomIn.addEventListener('click', () => { zoom = Math.min(zoom + 0.25, 3); update(); });
  if (zoomOut) zoomOut.addEventListener('click', () => { zoom = Math.max(zoom - 0.25, 0.5); update(); });

  let dragging = false;
  let startX, startY;

  if (img) {
    img.addEventListener('mousedown', (e) => {
      dragging = true;
      startX = e.clientX - offsetX;
      startY = e.clientY - offsetY;
    });
    document.addEventListener('mousemove', (e) => {
      if (dragging) {
        offsetX = e.clientX - startX;
        offsetY = e.clientY - startY;
        update();
      }
    });
    document.addEventListener('mouseup', () => { dragging = false; });

    img.addEventListener('touchstart', (e) => {
      dragging = true;
      const t = e.touches[0];
      startX = t.clientX - offsetX;
      startY = t.clientY - offsetY;
    });
    document.addEventListener('touchmove', (e) => {
      if (dragging) {
        const t = e.touches[0];
        offsetX = t.clientX - startX;
        offsetY = t.clientY - startY;
        update();
      }
    });
    document.addEventListener('touchend', () => { dragging = false; });
  }

  update();
}

