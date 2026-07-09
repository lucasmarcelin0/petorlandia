// Web Push — opt-in e sincronização da inscrição.
// Requer: service worker registrado no layout e <meta name="csrf-token">.
(function () {
  'use strict';

  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; i += 1) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  async function serverConfig() {
    const resp = await fetch('/push/vapid-public-key', { headers: { Accept: 'application/json' } });
    if (!resp.ok) return { enabled: false };
    return resp.json();
  }

  async function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        Accept: 'application/json',
      },
      body: JSON.stringify(body || {}),
    });
  }

  async function getSubscription() {
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  }

  async function subscribe() {
    const cfg = await serverConfig();
    if (!cfg.enabled || !cfg.publicKey) return false;

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return false;

    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.publicKey),
      });
    }
    const resp = await postJson('/push/subscribe', { subscription: sub.toJSON() });
    if (resp.ok) {
      postJson('/push/test', {});
      return true;
    }
    return false;
  }

  async function unsubscribe() {
    const sub = await getSubscription();
    if (!sub) return true;
    await postJson('/push/unsubscribe', { endpoint: sub.endpoint });
    await sub.unsubscribe();
    return true;
  }

  // Re-sincroniza a inscrição existente (endpoint pode mudar de dono/expirar).
  async function syncIfGranted() {
    if (Notification.permission !== 'granted') return;
    const sub = await getSubscription();
    if (sub) {
      postJson('/push/subscribe', { subscription: sub.toJSON() }).catch(() => {});
    }
  }

  async function initUi() {
    const item = document.getElementById('push-toggle-item');
    if (!item) return;
    if (!supported) {
      item.classList.add('d-none');
      return;
    }
    const cfg = await serverConfig();
    if (!cfg.enabled) {
      item.classList.add('d-none');
      return;
    }

    const link = item.querySelector('a');
    const label = item.querySelector('[data-push-label]');

    async function render() {
      const sub = Notification.permission === 'granted' ? await getSubscription() : null;
      if (sub) {
        label.textContent = 'Notificações ativadas';
        link.dataset.pushState = 'on';
      } else {
        label.textContent = 'Ativar notificações';
        link.dataset.pushState = 'off';
      }
      item.classList.remove('d-none');
    }

    link.addEventListener('click', async (ev) => {
      ev.preventDefault();
      if (link.dataset.pushState === 'on') {
        await unsubscribe();
      } else {
        await subscribe();
      }
      render();
    });

    render();
  }

  if (supported) {
    document.addEventListener('DOMContentLoaded', () => {
      initUi();
      syncIfGranted();
    });
  } else {
    document.addEventListener('DOMContentLoaded', initUi);
  }

  window.PetPush = { subscribe, unsubscribe };
})();
