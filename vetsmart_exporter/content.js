// VetSmart Exporter - content.js
// Injeta um script inline na pagina para acessar o contexto real do JS.
// Content scripts tem mundo isolado, mas podem injetar scripts no mundo da pagina.

(function () {
  'use strict';

  function runInPageContext(fn) {
    return new Promise((resolve) => {
      const scriptId = '__vetsmart_exporter_bridge__';
      const resultKey = '__vetsmart_exporter_result__';

      const old = document.getElementById(scriptId);
      if (old) old.remove();
      delete window[resultKey];

      const script = document.createElement('script');
      script.id = scriptId;
      script.textContent = `
        (function() {
          const result = (${fn.toString()})();
          window['${resultKey}'] = JSON.stringify(result);
        })();
      `;
      document.documentElement.appendChild(script);
      script.remove();

      resolve(window[resultKey] ? JSON.parse(window[resultKey]) : null);
    });
  }

  function parseStorageValue(value) {
    if (typeof value !== 'string') return value;
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }

  function prioritizeStorageKeys(keys) {
    const priorityPatterns = [
      /sessiontoken/i,
      /currentuser/i,
      /parse/i,
      /user/i,
      /token/i,
      /auth/i,
      /access/i,
      /session/i
    ];

    return [...keys].sort((a, b) => scoreStorageKey(b) - scoreStorageKey(a));

    function scoreStorageKey(key) {
      return priorityPatterns.reduce((score, pattern, index) => (
        pattern.test(key) ? score + (priorityPatterns.length - index) * 10 : score
      ), 0);
    }
  }

  function extractTokenString(val, key) {
    if (!val) return null;

    if (typeof key === 'string' && /sessiontoken/i.test(key) && typeof val === 'string' && val.length > 10) {
      return val;
    }

    if (typeof val === 'string') {
      if (/^r:[a-z0-9]+$/i.test(val)) return val;
      if (val.length > 20 && (val.includes('.') || val.startsWith('ey'))) return val;
      if (val.length > 30) return val;
      return null;
    }

    if (typeof val === 'object') {
      if (typeof val.sessionToken === 'string' && val.sessionToken.length > 10) {
        return val.sessionToken;
      }

      const fields = [
        'sessionToken',
        'token',
        'access_token',
        'accessToken',
        'jwt',
        'bearer',
        'id_token',
        'idToken',
        'Authorization'
      ];

      for (const field of fields) {
        const candidate = val[field];
        if (typeof candidate === 'string') {
          if (/^r:[a-z0-9]+$/i.test(candidate)) return candidate;
          if (candidate.length > 20) return candidate;
        }
      }

      for (const [childKey, childValue] of Object.entries(val)) {
        if (typeof childValue === 'string') {
          if (/^r:[a-z0-9]+$/i.test(childValue)) return childValue;
          if (childValue.length > 30) return childValue;
          continue;
        }

        if (childValue && typeof childValue === 'object') {
          const nested = extractTokenString(childValue, childKey);
          if (nested) return nested;
        }
      }
    }

    return null;
  }

  function collectTokenFromPage() {
    try {
      const ls = window.localStorage;
      const keys = Object.keys(ls);
      const found = {};
      const parseValue = (value) => {
        if (typeof value !== 'string') return value;
        try {
          return JSON.parse(value);
        } catch {
          return value;
        }
      };

      for (const key of keys) {
        try {
          found[key] = parseValue(ls.getItem(key));
        } catch (_) {}
      }

      return {
        tokenCandidates: found,
        allKeys: keys
      };
    } catch (e) {
      return { error: e.message, tokenCandidates: {}, allKeys: [] };
    }
  }

  async function detectToken() {
    try {
      const ls = window.localStorage;
      const keys = Object.keys(ls);

      for (const key of prioritizeStorageKeys(keys)) {
        try {
          const parsed = parseStorageValue(ls.getItem(key));
          const token = extractTokenString(parsed, key);
          if (token) {
            return { token, source: `localStorage:${key}`, allKeys: keys };
          }
        } catch (_) {}
      }

      return { token: null, source: null, allKeys: keys };
    } catch (e) {
      const result = await runInPageContext(collectTokenFromPage);
      if (result) {
        for (const key of prioritizeStorageKeys(Object.keys(result.tokenCandidates || {}))) {
          const token = extractTokenString(result.tokenCandidates[key], key);
          if (token) {
            return { token, source: `pageContext:${key}`, allKeys: result.allKeys || [] };
          }
        }
        return { token: null, source: 'pageContext', allKeys: result.allKeys || [] };
      }

      return { token: null, source: null, allKeys: [], error: e.message };
    }
  }

  async function fetchTutors(token, page = 1, perPage = 50) {
    const url = `https://prontuario.vetsmart.com.br/api/v1/clients?page=${page}&per_page=${perPage}`;
    const resp = await fetchWithAuthVariants(url, token);
    return resp.json();
  }

  async function fetchAnimals(token, clientId) {
    const url = `https://prontuario.vetsmart.com.br/api/v1/clients/${clientId}/patients`;
    const resp = await fetchWithAuthVariants(url, token);
    return resp.json();
  }

  async function fetchWithAuthVariants(url, token) {
    const variants = buildAuthVariants(token);
    const failures = [];

    for (const variant of variants) {
      try {
        const resp = await fetch(url, {
          method: 'GET',
          headers: variant.headers,
          credentials: 'include'
        });

        if (resp.ok) {
          return resp;
        }

        failures.push(`${variant.label}: HTTP ${resp.status}`);
      } catch (error) {
        failures.push(`${variant.label}: ${error.message}`);
      }
    }

    throw new Error(`Falha de autenticacao na API do VetSmart (${failures.join(' | ')})`);
  }

  function buildHeaders(token) {
    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };

    if (token) {
      if (token.startsWith('ey') || token.includes('.')) {
        headers.Authorization = `Bearer ${token}`;
      } else {
        headers.Authorization = token;
        headers['X-Auth-Token'] = token;
        headers['X-Parse-Session-Token'] = token;
      }
    }

    return headers;
  }

  function buildAuthVariants(token) {
    const variants = [];
    const baseHeaders = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };

    variants.push({ label: 'cookie-only', headers: { ...baseHeaders } });

    if (!token) {
      return variants;
    }

    if (token.startsWith('ey') || token.includes('.')) {
      variants.unshift({
        label: 'bearer-jwt',
        headers: { ...baseHeaders, Authorization: `Bearer ${token}` }
      });
      return dedupeVariants(variants);
    }

    variants.unshift(
      {
        label: 'parse-session-header',
        headers: { ...baseHeaders, 'X-Parse-Session-Token': token }
      },
      {
        label: 'raw-authorization',
        headers: { ...baseHeaders, Authorization: token }
      },
      {
        label: 'x-auth-token',
        headers: { ...baseHeaders, 'X-Auth-Token': token }
      },
      {
        label: 'all-session-headers',
        headers: {
          ...baseHeaders,
          Authorization: token,
          'X-Auth-Token': token,
          'X-Parse-Session-Token': token
        }
      },
      {
        label: 'bearer-session-token',
        headers: { ...baseHeaders, Authorization: `Bearer ${token}` }
      }
    );

    return dedupeVariants(variants);
  }

  function dedupeVariants(variants) {
    const seen = new Set();
    return variants.filter((variant) => {
      const key = JSON.stringify(variant.headers);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  async function exportAll(token, onProgress) {
    const tutors = [];
    const animals = [];
    let page = 1;
    let totalPages = 1;

    do {
      onProgress?.(`Buscando tutores - pagina ${page}/${totalPages}...`);
      const data = await fetchTutors(token, page);

      const items = Array.isArray(data)
        ? data
        : (data.data || data.clients || data.results || data.items || []);
      totalPages = data.total_pages || data.last_page || data.pages || 1;

      for (const tutor of items) {
        tutors.push(tutor);

        try {
          const animalsData = await fetchAnimals(token, tutor.id);
          const petList = Array.isArray(animalsData)
            ? animalsData
            : (animalsData.data || animalsData.patients || animalsData.results || []);

          for (const animal of petList) {
            animals.push({ ...animal, tutor_id: tutor.id, tutor_name: tutor.name || tutor.nome });
          }
        } catch (e) {
          console.warn(`[VetSmart] Nao foi possivel buscar animais do tutor ${tutor.id}:`, e);
        }
      }

      page++;
    } while (page <= totalPages);

    return { tutors, animals };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'GET_TOKEN') {
      detectToken()
        .then(result => sendResponse(result))
        .catch(e => sendResponse({ error: e.message }));
      return true;
    }

    if (message.action === 'GET_LS_KEYS') {
      try {
        const keys = Object.keys(window.localStorage);
        sendResponse({ keys });
      } catch (e) {
        sendResponse({ error: e.message, keys: [] });
      }
      return true;
    }

    if (message.action === 'EXPORT_ALL') {
      const token = message.token;
      exportAll(token, (msg) => {
        chrome.runtime.sendMessage({ action: 'PROGRESS', message: msg });
      })
        .then(data => sendResponse({ success: true, data }))
        .catch(e => sendResponse({ success: false, error: e.message }));
      return true;
    }

    if (message.action === 'PING') {
      sendResponse({ alive: true, url: window.location.href });
      return true;
    }
  });

  chrome.runtime.sendMessage({ action: 'CONTENT_READY', url: window.location.href });

  console.log('[VetSmart Exporter] content.js carregado em', window.location.href);
})();
