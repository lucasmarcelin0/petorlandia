function updateAvatarTransform(img, offsetX, offsetY, rotation, zoom) {
  if (!img) return;
  img.style.setProperty('--offset-x', (offsetX || 0) + 'px');
  img.style.setProperty('--offset-y', (offsetY || 0) + 'px');
  img.style.setProperty('--rotation', (rotation || 0) + 'deg');
  img.style.setProperty('--zoom', zoom || 1);
}

function initAvatarTransforms() {
  document.querySelectorAll('img.avatar').forEach(img => {
    const offsetX = parseFloat(img.dataset.offsetX) || 0;
    const offsetY = parseFloat(img.dataset.offsetY) || 0;
    const rotation = parseFloat(img.dataset.rotation) || 0;
    const zoom = parseFloat(img.dataset.zoom) || 1;
    updateAvatarTransform(img, offsetX, offsetY, rotation, zoom);
  });
}

document.addEventListener('DOMContentLoaded', initAvatarTransforms);
