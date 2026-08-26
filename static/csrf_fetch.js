/*
 * Anexa o token CSRF automaticamente em requisicoes mutantes same-origin.
 *
 * Motivo: o app usa CSRFProtect global, mas dezenas de chamadas fetch()/XHR
 * espalhadas em templates e scripts nao mandavam token nenhum. O resultado era
 * HTTP 400 com "CSRF token missing or invalid" — e como boa parte desse JS nao
 * checa a resposta, a acao falhava em silencio (o chat, por exemplo, limpava o
 * campo de texto e nunca enviava a mensagem).
 *
 * Este wrapper resolve a classe inteira num lugar so, em vez de depender de
 * cada call site lembrar do header. Precisa ser carregado ANTES de qualquer
 * script que faca requisicao.
 *
 * Regras:
 *  - so mexe em metodos mutantes (POST/PUT/PATCH/DELETE);
 *  - so em same-origin, para nunca vazar o token para terceiros;
 *  - nunca sobrescreve um X-CSRFToken que o call site ja definiu;
 *  - le o token do <meta name="csrf-token"> no momento da requisicao, para
 *    pegar o valor renovado se a pagina tiver atualizado a meta.
 *  - se o token venceu enquanto a tela ficou aberta, busca um token novo e
 *    repete a requisicao uma unica vez (sem perder o formulario/foto).
 */
(function () {
  'use strict';

  var MUTATING = /^(POST|PUT|PATCH|DELETE)$/i;
  var HEADER = 'X-CSRFToken';
  var REFRESH_URL = '/csrf-token';
  var refreshPromise = null;

  function currentToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.content) || '';
  }

  function updateToken(token) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && token) {
      meta.content = token;
    }
  }

  function isSameOrigin(url) {
    // URL relativa (inclusive '', '/x', '?a=1') e sempre same-origin.
    try {
      var resolved = new URL(url, window.location.href);
      return resolved.origin === window.location.origin;
    } catch (error) {
      // Se nao conseguimos resolver, e mais seguro NAO anexar o token.
      return false;
    }
  }

  // --- fetch ---------------------------------------------------------------
  var nativeFetch = window.fetch;
  if (typeof nativeFetch === 'function') {
    function isCsrfFailure(response) {
      if (!response || Number(response.status) !== 400 || typeof response.clone !== 'function') {
        return Promise.resolve(false);
      }
      return response.clone().json().then(function (payload) {
        return Boolean(
          payload && (
            payload.error === 'CSRF token missing or invalid' ||
            (payload.errors && payload.errors.csrf_token)
          )
        );
      }).catch(function () {
        return false;
      });
    }

    function refreshCsrfToken() {
      if (!refreshPromise) {
        refreshPromise = nativeFetch.call(window, REFRESH_URL, {
          method: 'GET',
          headers: { 'Accept': 'application/json' },
          credentials: 'same-origin',
          cache: 'no-store',
        }).then(function (response) {
          if (!response || !response.ok) {
            throw new Error('Nao foi possivel renovar o token CSRF.');
          }
          return response.json();
        }).then(function (payload) {
          var token = payload && payload.csrf_token;
          if (!token) {
            throw new Error('Resposta de renovacao CSRF sem token.');
          }
          updateToken(token);
          return token;
        }).finally(function () {
          refreshPromise = null;
        });
      }
      return refreshPromise;
    }

    function requestOptions(resource, init, forceFreshToken) {
      var options = init || {};
      var isRequest = typeof Request !== 'undefined' && resource instanceof Request;
      var method = options.method || (isRequest ? resource.method : 'GET') || 'GET';
      var token = currentToken();
      if (!MUTATING.test(method) || !isSameOrigin(isRequest ? resource.url : resource) || !token) {
        return { options: init, mutating: false };
      }

      var headers = new Headers(
        options.headers || (isRequest ? resource.headers : undefined) || {}
      );
      if (forceFreshToken || !headers.has(HEADER)) {
        headers.set(HEADER, token);
      }

      var nextInit = {};
      for (var key in options) {
        if (Object.prototype.hasOwnProperty.call(options, key)) {
          nextInit[key] = options[key];
        }
      }
      nextInit.headers = headers;
      if (!nextInit.method && isRequest) {
        nextInit.method = method;
      }
      return { options: nextInit, mutating: true };
    }

    window.fetch = function (resource, init) {
      var options = init || {};
      var isRequest = typeof Request !== 'undefined' && resource instanceof Request;
      var url = isRequest ? resource.url : resource;
      var method = options.method || (isRequest ? resource.method : 'GET') || 'GET';

      if (!MUTATING.test(method) || !isSameOrigin(url)) {
        return nativeFetch.call(this, resource, init);
      }

      var first = requestOptions(resource, init, false);
      var retryResource = (
        isRequest && typeof resource.clone === 'function'
      ) ? resource.clone() : resource;
      var canRetry = !isRequest || retryResource !== resource;

      return nativeFetch.call(this, resource, first.options).then(function (response) {
        return isCsrfFailure(response).then(function (failed) {
          if (!failed || !canRetry) return response;
          return refreshCsrfToken().then(function () {
            var retry = requestOptions(retryResource, init, true);
            return nativeFetch.call(window, retryResource, retry.options);
          }).catch(function () {
            // Mantem a resposta original: o call site continua recebendo o
            // erro real caso a sessao tenha acabado por completo.
            return response;
          });
        });
      });
    };
    window.fetch.__csrfWrapped = true;
  }

  // --- XMLHttpRequest ------------------------------------------------------
  var XHR = window.XMLHttpRequest;
  if (XHR && XHR.prototype) {
    var nativeOpen = XHR.prototype.open;
    var nativeSend = XHR.prototype.send;

    XHR.prototype.open = function (method, url) {
      this.__csrfMethod = method;
      this.__csrfSameOrigin = isSameOrigin(url);
      this.__csrfHeaderSet = false;
      return nativeOpen.apply(this, arguments);
    };

    var nativeSetHeader = XHR.prototype.setRequestHeader;
    XHR.prototype.setRequestHeader = function (name) {
      if (typeof name === 'string' && name.toLowerCase() === HEADER.toLowerCase()) {
        this.__csrfHeaderSet = true;
      }
      return nativeSetHeader.apply(this, arguments);
    };

    XHR.prototype.send = function () {
      if (
        MUTATING.test(this.__csrfMethod || '') &&
        this.__csrfSameOrigin &&
        !this.__csrfHeaderSet
      ) {
        var token = currentToken();
        if (token) {
          try {
            nativeSetHeader.call(this, HEADER, token);
          } catch (error) {
            // Header ja enviado / estado invalido: segue sem quebrar a chamada.
          }
        }
      }
      return nativeSend.apply(this, arguments);
    };
    XHR.prototype.send.__csrfWrapped = true;
  }
})();
