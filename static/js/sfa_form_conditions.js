(function (root, factory) {
  const api = factory(root && root.document ? root.document : null);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SfaFormConditions = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (documentRef) {
  "use strict";

  const normalize = (value) => String(value == null ? "" : value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();

  const asList = (value) => Array.isArray(value)
    ? value.filter((item) => String(item == null ? "" : item).trim() !== "")
    : (String(value == null ? "" : value).trim() ? [value] : []);

  const hasValue = (value) => asList(value).length > 0;

  const equals = (left, right) => {
    const expected = normalize(right);
    return asList(left).some((item) => normalize(item) === expected);
  };

  const intersects = (left, values) => {
    const expected = new Set(asList(values).map(normalize));
    return asList(left).some((item) => expected.has(normalize(item)));
  };

  const isPositive = (value) => asList(value)
    .some((item) => normalize(item).startsWith("sim"));

  const evaluateAtomic = (rule, getValue) => {
    const source = normalize(rule.source || "current");
    if (source && source !== "current") return false;

    const key = String(rule.key || rule.field || "").trim();
    if (!key) return true;
    const value = getValue(key);
    const operator = normalize(rule.operator || rule.op || "equals").replace(/\s+/g, "_");

    if (["equals", "eq"].includes(operator)) return equals(value, rule.value);
    if (["not_equals", "neq"].includes(operator)) return !equals(value, rule.value);
    if (operator === "in") return intersects(value, rule.values || []);
    if (["selected_any", "contains_any"].includes(operator)) {
      const options = rule.values || [];
      return asList(options).length ? intersects(value, options) : hasValue(value);
    }
    if (operator === "selected_any_except") {
      const excluded = new Set(asList(rule.values || []).map(normalize));
      return asList(value).some((item) => !excluded.has(normalize(item)));
    }
    if (["nonempty", "present"].includes(operator)) return hasValue(value);
    if (operator === "absent") return !hasValue(value);
    if (operator === "positive") return isPositive(value);
    return false;
  };

  const evaluateRule = (rule, getValue) => {
    if (!rule || typeof rule !== "object") return true;
    if (Object.prototype.hasOwnProperty.call(rule, "const")) return Boolean(rule.const);
    if (Array.isArray(rule.all)) return rule.all.every((item) => evaluateRule(item, getValue));
    if (Array.isArray(rule.any)) return rule.any.some((item) => evaluateRule(item, getValue));
    if (rule.not && typeof rule.not === "object") return !evaluateRule(rule.not, getValue);

    // Compatibilidade com instrumentos anteriores.
    if (rule.current_positive && typeof rule.current_positive === "object") {
      return isPositive(getValue(rule.current_positive.key));
    }
    if (rule.no_prior_positive && typeof rule.no_prior_positive === "object") {
      return true; // O servidor converte esta regra em constante antes de renderizar.
    }
    return evaluateAtomic(rule, getValue);
  };

  const fieldValues = (documentObj, name) => {
    const rawName = String(name || "");
    const candidateNames = [rawName, "answer__" + rawName];
    let fields = [];
    for (const candidateName of candidateNames) {
      const escaped = candidateName.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
      fields = Array.from(documentObj.querySelectorAll('[name="' + escaped + '"]'));
      if (fields.length) break;
    }
    if (!fields.length) return "";
    const first = fields[0];
    if (first.type === "checkbox") return fields.filter((field) => field.checked).map((field) => field.value);
    if (first.type === "radio") {
      const checked = fields.find((field) => field.checked);
      return checked ? checked.value : "";
    }
    return first.value;
  };

  const clearControls = (container) => {
    container.querySelectorAll("input, select, textarea").forEach((field) => {
      if (field.type === "checkbox" || field.type === "radio") field.checked = false;
      else field.value = "";
    });
  };

  const setControlsEnabled = (container, visible) => {
    const controls = Array.from(container.querySelectorAll("input, select, textarea"));
    controls.forEach((field) => {
      field.disabled = !visible;
      if (field.dataset.conditionalRequired === "true") {
        field.required = visible && field.type !== "checkbox";
      }
    });
  };

  const updateSections = (documentObj) => {
    documentObj.querySelectorAll("section.section").forEach((section) => {
      const fields = Array.from(section.querySelectorAll(".field, .question[data-review-question]"));
      if (!fields.length) return;
      const hasVisibleField = fields.some((field) => !field.hidden);
      section.hidden = !hasVisibleField;
      section.setAttribute("aria-hidden", hasVisibleField ? "false" : "true");
    });
  };

  const updateConditionalFields = (documentObj) => {
    const getValue = (name) => fieldValues(documentObj, name);
    documentObj.querySelectorAll("[data-visible-if]").forEach((container) => {
      let rule = {};
      try { rule = JSON.parse(container.dataset.visibleIf || "{}"); } catch (_error) { rule = {}; }
      const visible = evaluateRule(rule, getValue);
      if (!visible) clearControls(container);
      container.hidden = !visible;
      container.dataset.conditionReady = "true";
      container.setAttribute("aria-hidden", visible ? "false" : "true");
      setControlsEnabled(container, visible);
    });
    updateSections(documentObj);
  };

  const installNoneExclusivity = (documentObj) => {
    documentObj.querySelectorAll(".choices").forEach((group) => {
      const boxes = Array.from(group.querySelectorAll('input[type="checkbox"]'));
      if (!boxes.length) return;
      const isNone = (value) => {
        const normalized = normalize(value);
        return normalized.startsWith("nenhum") || normalized.startsWith("nenhuma") || normalized === "nao sei";
      };
      boxes.forEach((box) => box.addEventListener("change", () => {
        if (!box.checked) return;
        boxes.forEach((other) => {
          if (other !== box && (isNone(box.value) || isNone(other.value))) other.checked = false;
        });
      }));
    });
  };

  const init = (documentObj) => {
    if (!documentObj) return;
    documentObj.querySelectorAll("[data-visible-if]").forEach((container) => {
      container.querySelectorAll("input[required], select[required], textarea[required]").forEach((field) => {
        field.dataset.conditionalRequired = "true";
      });
    });
    installNoneExclusivity(documentObj);
    documentObj.addEventListener("change", () => updateConditionalFields(documentObj));
    documentObj.addEventListener("input", () => updateConditionalFields(documentObj));
    updateConditionalFields(documentObj);
  };

  if (documentRef) {
    if (documentRef.readyState === "loading") documentRef.addEventListener("DOMContentLoaded", () => init(documentRef));
    else init(documentRef);
  }

  return { normalize, asList, evaluateRule, fieldValues, updateConditionalFields, init };
});
