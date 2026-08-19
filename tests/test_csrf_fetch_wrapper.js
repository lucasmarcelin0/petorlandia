/*
 * Exercita static/csrf_fetch.js de verdade, contra stubs minimos de DOM.
 *
 * Rodado por tests/test_csrf_ajax_guard.py::test_wrapper_behaviour_suite_passes.
 * Sem este arquivo, o guard Python so provaria que o wrapper existe e contem
 * certas palavras — nao que ele anexa o header certo nos casos certos.
 *
 * Uso direto: node tests/test_csrf_fetch_wrapper.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WRAPPER = path.join(__dirname, '..', 'static', 'csrf_fetch.js');
const TOKEN = 'token-de-teste-123';

let failures = 0;
let passes = 0;

function check(name, condition, detail) {
  if (condition) {
    passes += 1;
  } else {
    failures += 1;
    console.error(`FALHOU: ${name}${detail ? ' — ' + detail : ''}`);
  }
}

/* Monta um ambiente novo com o wrapper aplicado. */
function buildEnv(options) {
  const opts = options || {};
  const metaContent = 'metaToken' in opts ? opts.metaToken : TOKEN;
  const calls = [];
  const xhrCalls = [];

  const sandbox = {
    console,
    URL,
    Headers,
    Request: class Request {
      constructor(url, init) {
        const cfg = init || {};
        this.url = url;
        this.method = cfg.method || 'GET';
        this.headers = new Headers(cfg.headers || {});
      }
    },
    document: {
      querySelector(selector) {
        if (selector === 'meta[name="csrf-token"]' && metaContent !== null) {
          return { content: metaContent };
        }
        return null;
      },
    },
    window: {
      location: { href: 'https://app.example.com/pagina', origin: 'https://app.example.com' },
      fetch(resource, init) {
        calls.push({ resource, init });
        return Promise.resolve({ ok: true });
      },
    },
  };

  // XHR stub que registra headers definidos.
  function FakeXHR() {
    this.headers = {};
    this.sent = false;
  }
  FakeXHR.prototype.open = function (method, url) {
    this.method = method;
    this.url = url;
  };
  FakeXHR.prototype.setRequestHeader = function (name, value) {
    this.headers[name] = value;
  };
  FakeXHR.prototype.send = function () {
    this.sent = true;
    xhrCalls.push(this);
  };
  sandbox.window.XMLHttpRequest = FakeXHR;

  sandbox.window.window = sandbox.window;
  sandbox.window.document = sandbox.document;
  sandbox.window.URL = URL;
  sandbox.window.Headers = Headers;
  sandbox.window.Request = sandbox.Request;
  sandbox.XMLHttpRequest = FakeXHR;

  const context = vm.createContext(sandbox);
  const code = fs.readFileSync(WRAPPER, 'utf8');
  vm.runInContext(code, context);

  return { sandbox, calls, xhrCalls };
}

function headerOf(init) {
  if (!init || !init.headers) return undefined;
  const headers = init.headers instanceof Headers ? init.headers : new Headers(init.headers);
  return headers.get('X-CSRFToken') || undefined;
}

/* ---------------------------------------------------------------- fetch --- */

(function postSameOriginGetsToken() {
  const env = buildEnv();
  env.sandbox.window.fetch('/chat/1', { method: 'POST', body: '{}' });
  check(
    'POST same-origin recebe X-CSRFToken',
    headerOf(env.calls[0].init) === TOKEN,
    `header=${headerOf(env.calls[0].init)}`
  );
})();

['PUT', 'PATCH', 'DELETE'].forEach(function (method) {
  const env = buildEnv();
  env.sandbox.window.fetch('/vacina/1', { method: method });
  check(`${method} same-origin recebe token`, headerOf(env.calls[0].init) === TOKEN);
});

(function getDoesNotGetToken() {
  const env = buildEnv();
  env.sandbox.window.fetch('/animais');
  check('GET nao recebe token', headerOf(env.calls[0].init) === undefined);
})();

(function crossOriginNeverGetsToken() {
  const env = buildEnv();
  env.sandbox.window.fetch('https://malicioso.example.net/coleta', { method: 'POST' });
  check(
    'cross-origin NAO recebe token',
    headerOf(env.calls[0].init) === undefined,
    'token vazaria para terceiro'
  );
})();

(function protocolRelativeCrossOriginBlocked() {
  const env = buildEnv();
  env.sandbox.window.fetch('//malicioso.example.net/x', { method: 'POST' });
  check(
    'URL protocol-relative para outro host NAO recebe token',
    headerOf(env.calls[0].init) === undefined
  );
})();

(function absoluteSameOriginGetsToken() {
  const env = buildEnv();
  env.sandbox.window.fetch('https://app.example.com/racao/1', { method: 'PUT' });
  check('URL absoluta same-origin recebe token', headerOf(env.calls[0].init) === TOKEN);
})();

(function existingHeaderNotOverwritten() {
  const env = buildEnv();
  env.sandbox.window.fetch('/x', {
    method: 'POST',
    headers: { 'X-CSRFToken': 'token-do-call-site' },
  });
  check(
    'header pre-existente e preservado',
    headerOf(env.calls[0].init) === 'token-do-call-site'
  );
})();

(function otherHeadersPreserved() {
  const env = buildEnv();
  env.sandbox.window.fetch('/x', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  const headers = new Headers(env.calls[0].init.headers);
  check(
    'Content-Type original preservado',
    headers.get('Content-Type') === 'application/json' &&
      headers.get('X-CSRFToken') === TOKEN
  );
})();

(function otherInitOptionsPreserved() {
  const env = buildEnv();
  env.sandbox.window.fetch('/x', { method: 'POST', body: 'abc', credentials: 'same-origin' });
  const init = env.calls[0].init;
  check(
    'body e credentials preservados',
    init.body === 'abc' && init.credentials === 'same-origin'
  );
})();

(function requestObjectSupported() {
  const env = buildEnv();
  const req = new env.sandbox.Request('/x', { method: 'POST' });
  env.sandbox.window.fetch(req);
  check(
    'Request object com POST recebe token',
    headerOf(env.calls[0].init) === TOKEN,
    `header=${headerOf(env.calls[0].init)}`
  );
})();

(function noMetaMeansNoCrash() {
  const env = buildEnv({ metaToken: null });
  let threw = false;
  try {
    env.sandbox.window.fetch('/x', { method: 'POST' });
  } catch (error) {
    threw = true;
  }
  check('sem meta token nao quebra a chamada', !threw && env.calls.length === 1);
  check('sem meta token nao inventa header', headerOf(env.calls[0].init) === undefined);
})();

(function lowercaseMethodHandled() {
  const env = buildEnv();
  env.sandbox.window.fetch('/x', { method: 'post' });
  check('metodo minusculo tambem recebe token', headerOf(env.calls[0].init) === TOKEN);
})();

/* ------------------------------------------------------------------ XHR --- */

(function xhrPostGetsToken() {
  const env = buildEnv();
  const xhr = new env.sandbox.window.XMLHttpRequest();
  xhr.open('POST', '/x');
  xhr.send('a=1');
  check('XHR POST recebe token', xhr.headers['X-CSRFToken'] === TOKEN);
})();

(function xhrGetDoesNot() {
  const env = buildEnv();
  const xhr = new env.sandbox.window.XMLHttpRequest();
  xhr.open('GET', '/x');
  xhr.send();
  check('XHR GET nao recebe token', xhr.headers['X-CSRFToken'] === undefined);
})();

(function xhrCrossOriginDoesNot() {
  const env = buildEnv();
  const xhr = new env.sandbox.window.XMLHttpRequest();
  xhr.open('POST', 'https://malicioso.example.net/x');
  xhr.send();
  check('XHR cross-origin nao recebe token', xhr.headers['X-CSRFToken'] === undefined);
})();

(function xhrExistingHeaderPreserved() {
  const env = buildEnv();
  const xhr = new env.sandbox.window.XMLHttpRequest();
  xhr.open('POST', '/x');
  xhr.setRequestHeader('X-CSRFToken', 'do-call-site');
  xhr.send();
  check('XHR header pre-existente preservado', xhr.headers['X-CSRFToken'] === 'do-call-site');
})();

/* --------------------------------------------------------------- report --- */

if (failures) {
  console.error(`\n${failures} verificacao(oes) falharam, ${passes} passaram.`);
  process.exit(1);
}
console.log(`OK: ${passes} verificacoes do wrapper CSRF passaram.`);
