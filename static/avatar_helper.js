function updateAvatarTransform(img) {
  if (!img) return;
  const offsetX = img.dataset.offsetX || 0;
  const offsetY = img.dataset.offsetY || 0;
  const rotation = img.dataset.rotation || 0;
  const zoom = img.dataset.zoom || 1;
  img.style.setProperty('--avatar-offset-x', `${offsetX}px`);
  img.style.setProperty('--avatar-offset-y', `${offsetY}px`);
  img.style.setProperty('--avatar-rotation', `${rotation}deg`);
  img.style.setProperty('--avatar-zoom', zoom);
}

function applyAvatarTransforms() {
  document.querySelectorAll('.avatar').forEach(updateAvatarTransform);
}

document.addEventListener('DOMContentLoaded', applyAvatarTransforms);
