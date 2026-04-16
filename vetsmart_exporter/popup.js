// VetSmart Exporter - popup.js
'use strict';

let detectedToken = null;
let exportedData = null;

const $ = id => document.getElementById(id);

// ─── Inicialização ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setStatus('yellow', 'Verificando aba do VetSmart...');
  $('btnDetectToken').disabled = true;
  $('btnShowKeys').disabled = true;

  // Verifica se há aba aberta do VetSmart
  const status = await msg('GET_STATUS');

  if (status?.error) {
    setStatus('red', `Erro: ${status.error}`);
    $('btnDetectToken').disabled = false;
    $('btnShowKeys').style.display = 'block';
    $('btnShowKeys').disabled = false;
    addLog(`❌ ${status.error}`, 'error');
    return;
  }

  if (status?.status === 'no_tab') {
    setStatus('red', 'Abra prontuario.vetsmart.com.br primeiro');
    $('btnDetectToken').disabled = true;
    return;
  }

  $('btnDetectToken').disabled = false;
  $('btnShowKeys').style.display = 'block';
  $('btnShowKeys').disabled = false;

  if (status?.status === 'ready') {
    setStatus('green', 'VetSmart detectado! Clique em "Detectar Token"');
    if (status.url) {
      addLog(`✅ Aba detectada: ${status.url}`, 'success');
    }
  } else {
    setStatus('yellow', 'VetSmart encontrado, mas a conexao com a aba falhou');
    if (status?.url) {
      addLog(`ℹ Aba encontrada: ${status.url}`, '');
    }
    addLog('⚠ Vamos tentar detectar o token mesmo assim.', 'error');
  }
});

// ─── Botão: Detectar Token ────────────────────────────────────────────────
$('btnDetectToken').addEventListener('click', async () => {
  setStatus('yellow', 'Buscando token...');
  $('btnDetectToken').disabled = true;
  $('btnShowKeys').disabled = true;

  const result = await msg('FETCH_TOKEN');

  if (result?.error) {
    setStatus('red', `Erro: ${result.error}`);
    $('btnDetectToken').disabled = false;
    $('btnShowKeys').disabled = false;
    addLog(`❌ ${result.error}`, 'error');
    return;
  }

  if (result?.token) {
    detectedToken = result.token;
    $('tokenBox').style.display = 'block';
    $('tokenVal').textContent = result.token.length > 80
      ? result.token.substring(0, 80) + '...'
      : result.token;
    setStatus('green', `Token encontrado via ${result.source}`);
    $('btnExport').style.display = 'block';
    $('btnExport').disabled = false;
    $('btnShowKeys').disabled = false;
  } else {
    // Nenhum token encontrado — mostra as chaves disponíveis
    setStatus('yellow', 'Token não encontrado automaticamente');
    if (result?.allKeys?.length > 0) {
      showKeys(result.allKeys);
      addLog(`⚠ Nenhum token detectado automaticamente. Chaves disponíveis: ${result.allKeys.length}`, 'error');
      addLog('ℹ Consulte as chaves abaixo e informe qual contém o token.', '');
    } else {
      addLog('⚠ localStorage vazio ou inacessível. Verifique se está logado no VetSmart.', 'error');
    }
    $('btnDetectToken').disabled = false;
    $('btnShowKeys').disabled = false;
  }
});

// ─── Botão: Ver chaves do localStorage ────────────────────────────────────
$('btnShowKeys').addEventListener('click', async () => {
  const result = await msg('FETCH_LS_KEYS');
  if (result?.keys) {
    showKeys(result.keys);
  } else {
    addLog('Erro ao buscar chaves: ' + (result?.error || 'desconhecido'), 'error');
  }
});

// ─── Botão: Exportar ──────────────────────────────────────────────────────
$('btnExport').addEventListener('click', async () => {
  if (!detectedToken) {
    addLog('Nenhum token disponível. Detecte o token primeiro.', 'error');
    return;
  }

  $('btnExport').disabled = true;
  $('progressArea').classList.add('visible');
  setStatus('yellow', 'Exportando...');
  addLog('🚀 Iniciando exportação...', '');

  // Ouve mensagens de progresso
  const progressHandler = (message) => {
    if (message.action === 'PROGRESS_UPDATE') {
      addLog(message.message, '');
    }
  };
  chrome.runtime.onMessage.addListener(progressHandler);

  const result = await msg('START_EXPORT', { token: detectedToken });

  chrome.runtime.onMessage.removeListener(progressHandler);

  if (result?.success) {
    exportedData = result.data;
    const { tutors, animals } = result.data;
    setStatus('green', `Exportação concluída!`);
    addLog(`✅ ${tutors.length} tutores e ${animals.length} animais exportados`, 'success');
    $('resultArea').classList.add('visible');
    $('resultArea').innerHTML = `
      <strong>Exportação concluída!</strong><br>
      👤 <strong>${tutors.length}</strong> tutores<br>
      🐾 <strong>${animals.length}</strong> animais<br>
      <small>Clique em "Baixar JSON" para salvar os dados.</small>
    `;
    $('btnDownload').style.display = 'block';
  } else {
    setStatus('red', 'Erro na exportação');
    addLog(`❌ Erro: ${result?.error || 'desconhecido'}`, 'error');
    $('btnExport').disabled = false;
  }
});

// ─── Botão: Baixar JSON ────────────────────────────────────────────────────
$('btnDownload').addEventListener('click', () => {
  if (!exportedData) return;

  const blob = new Blob([JSON.stringify(exportedData, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `vetsmart_export_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

// ─── Helpers ──────────────────────────────────────────────────────────────
function setStatus(color, text) {
  const dot = $('statusDot');
  dot.className = `dot ${color}`;
  $('statusText').textContent = text;
}

function addLog(text, type = '') {
  const area = $('progressArea');
  area.classList.add('visible');
  const line = document.createElement('div');
  line.className = `progress-line ${type}`;
  line.textContent = text;
  area.appendChild(line);
  area.scrollTop = area.scrollHeight;
}

function showKeys(keys) {
  const area = $('keysArea');
  area.classList.add('visible');
  $('keysVal').innerHTML = keys.map(k => `<code>${k}</code>`).join(', ');
}

function msg(action, extra = {}) {
  return new Promise(resolve => {
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve({ error: `Tempo esgotado ao executar ${action}` });
    }, 8000);

    try {
      chrome.runtime.sendMessage({ action, ...extra }, resp => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);

        const runtimeError = chrome.runtime.lastError;
        if (runtimeError) {
          resolve({ error: runtimeError.message || `Falha ao executar ${action}` });
          return;
        }

        resolve(resp || { error: `Sem resposta para ${action}` });
      });
    } catch (error) {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve({ error: error.message || `Falha ao executar ${action}` });
    }
  });
}
