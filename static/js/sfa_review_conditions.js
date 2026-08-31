(function (root) {
  "use strict";

  const updateSummary = (documentObj) => {
    const summary = documentObj.querySelector("[data-sfa-condition-summary]");
    if (!summary) return;

    const questions = Array.from(documentObj.querySelectorAll("[data-review-question]"));
    const visible = questions.filter((question) => !question.hidden);
    const conditional = questions.filter((question) => question.hasAttribute("data-visible-if"));
    const openConditional = conditional.filter((question) => !question.hidden);
    const waitingConditional = conditional.length - openConditional.length;

    const questionLabel = visible.length === 1 ? " pergunta agora · " : " perguntas agora · ";
    const openLabel = openConditional.length === 1 ? " aprofundamento aberto · " : " aprofundamentos abertos · ";
    summary.textContent = visible.length + questionLabel
      + openConditional.length + openLabel
      + waitingConditional + " em espera";
  };

  const init = (documentObj) => {
    if (!documentObj) return;
    const scheduleUpdate = () => {
      if (root && typeof root.requestAnimationFrame === "function") {
        root.requestAnimationFrame(() => updateSummary(documentObj));
      } else {
        updateSummary(documentObj);
      }
    };
    documentObj.addEventListener("change", scheduleUpdate);
    documentObj.addEventListener("input", scheduleUpdate);
    scheduleUpdate();
  };

  if (typeof module === "object" && module.exports) module.exports = { updateSummary, init };
  if (root && root.document) {
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", () => init(root.document));
    } else {
      init(root.document);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
