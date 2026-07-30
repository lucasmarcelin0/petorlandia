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
 */
(function () {
  'use strict';

  var MUTATING = /^(POST|PUT|PATCH|DELETE)$/i;
  var HEADER = 'X-CSRFToken';

  function currentToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.content) || '';
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
    window.fetch = function (resource, init) {
      var options = init || {};
      var isRequest = typeof Request !== 'undefined' && resource instanceof Request;
      var url = isRequest ? resource.url : resource;
      var method = options.method || (isRequest ? resource.method : 'GET') || 'GET';

      if (!MUTATING.test(method) || !isSameOrigin(url)) {
        return nativeFetch.call(this, resource, init);
      }

      var token = currentToken();
      if (!token) {
        return nativeFetch.call(this, resource, init);
      }

      // Headers pode vir como Headers, array de pares ou objeto simples.
      var headers = new Headers(
        options.headers || (isRequest ? resource.headers : undefined) || {}
      );
      if (!headers.has(HEADER)) {
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
        // Preserva o metodo quando ele vinha so do Request.
        nextInit.method = method;
      }
      return nativeFetch.call(this, resource, nextInit);
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
