// VetSmart Exporter - background.js (Service Worker MV3)
'use strict';

// Estado global do service worker
let contentReady = false;
let lastTabId = null;

// ─── Listener de mensagens ────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'CONTENT_READY') {
    contentReady = true;
    lastTabId = sender.tab?.id;
    console.log('[BG] Content script pronto na aba', lastTabId, message.url);
    return;
  }

  if (message.action === 'PROGRESS') {
    // Repassa progresso para o popup se estiver aberto
    chrome.runtime.sendMessage({ action: 'PROGRESS_UPDATE', message: message.message })
      .catch(() => {}); // popup pode não estar aberto
    return;
  }
});

// ─── Inject content script se necessário ─────────────────────────────────
async function ensureContentScript(tabId) {
  try {
    // Testa se o content script já está ativo
    const resp = await chrome.tabs.sendMessage(tabId, { action: 'PING' });
    return resp?.alive === true;
  } catch (_) {
    // Content script não responde — injeta manualmente
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content.js']
      });
      // Aguarda um pouco para inicializar
      await new Promise(r => setTimeout(r, 500));
      return true;
    } catch (e) {
      console.error('[BG] Falha ao injetar content script:', e);
      return false;
    }
  }
}

// ─── Obtém aba ativa do VetSmart ──────────────────────────────────────────
async function getVetSmartTab() {
  const patterns = [
    'https://prontuario.vetsmart.com.br/*',
    'https://*.vetsmart.com.br/*'
  ];

  for (const pattern of patterns) {
    const activeTabs = await chrome.tabs.query({
      url: pattern,
      active: true,
      currentWindow: true
    });
    const activeTab = activeTabs.find(tab => isVetSmartProntuarioTab(tab));
    if (activeTab) return activeTab;
  }

  for (const pattern of patterns) {
    const tabs = await chrome.tabs.query({ url: pattern });
    const matchingTab = tabs.find(tab => isVetSmartProntuarioTab(tab));
    if (matchingTab) return matchingTab;
  }

  return null;
}

function isVetSmartProntuarioTab(tab) {
  if (!tab?.url) return false;

  try {
    const url = new URL(tab.url);
    return /(^|\.)prontuario\.vetsmart\.com\.br$/i.test(url.hostname);
  } catch (_) {
    return false;
  }
}

// ─── API pública usada pelo popup ─────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'GET_STATUS') {
    getVetSmartTab().then(tab => {
      if (!tab) {
        sendResponse({ status: 'no_tab', message: 'Nenhuma aba do VetSmart encontrada. Abra prontuario.vetsmart.com.br' });
        return;
      }
      ensureContentScript(tab.id).then(ok => {
        sendResponse({ status: ok ? 'ready' : 'error', tabId: tab.id, url: tab.url });
      });
    });
    return true;
  }

  if (message.action === 'FETCH_TOKEN') {
    getVetSmartTab().then(async tab => {
      if (!tab) { sendResponse({ error: 'Aba VetSmart não encontrada' }); return; }
      await ensureContentScript(tab.id);
      chrome.tabs.sendMessage(tab.id, { action: 'GET_TOKEN' }, result => {
        sendResponse(result || { error: 'Sem resposta do content script' });
      });
    });
    return true;
  }

  if (message.action === 'FETCH_LS_KEYS') {
    getVetSmartTab().then(async tab => {
      if (!tab) { sendResponse({ error: 'Aba VetSmart não encontrada' }); return; }
      await ensureContentScript(tab.id);
      chrome.tabs.sendMessage(tab.id, { action: 'GET_LS_KEYS' }, result => {
        sendResponse(result || { error: 'Sem resposta do content script' });
      });
    });
    return true;
  }

  if (message.action === 'START_EXPORT') {
    getVetSmartTab().then(async tab => {
      if (!tab) { sendResponse({ error: 'Aba VetSmart não encontrada' }); return; }
      await ensureContentScript(tab.id);
      chrome.tabs.sendMessage(tab.id, { action: 'EXPORT_ALL', token: message.token }, result => {
        sendResponse(result || { error: 'Sem resposta do content script' });
      });
    });
    return true;
  }
});
