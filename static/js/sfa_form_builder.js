(function () {
  const form = document.getElementById("schemaBuilderForm");
  if (!form) return;

  const SUPPORTED_FIELD_TYPES = [
    { value: "text", label: "Texto curto" },
    { value: "textarea", label: "Paragrafo" },
    { value: "date", label: "Data" },
    { value: "number", label: "Numero" },
    { value: "radio", label: "Multipla escolha" },
    { value: "select", label: "Lista suspensa" },
    { value: "checkboxes", label: "Caixas de selecao" },
  ];
  const CHOICE_TYPES = new Set(["radio", "select", "checkboxes"]);

  const hiddenInput = document.getElementById("schema_json");
  const rawTextarea = document.getElementById("schema_json_raw");
  const sectionsContainer = document.getElementById("sectionsContainer");
  const alertBox = document.getElementById("schemaEditorAlert");
  const titleInput = document.getElementById("formTitle");
  const subtitleInput = document.getElementById("formSubtitle");
  const submitLabelInput = document.getElementById("formSubmitLabel");
  const initialSchemaText = document.getElementById("schema-builder-data")?.textContent || "{}";
  const fallbackSchemaText = document.getElementById("schema-builder-fallback")?.textContent || "{}";

  let state = sanitizeSchema(parseInitialSchema());

  function parseInitialSchema() {
    try {
      return JSON.parse(initialSchemaText);
    } catch (_error) {
      try {
        return JSON.parse(fallbackSchemaText);
      } catch (_innerError) {
        return {};
      }
    }
  }

  function defaultField(type) {
    const resolvedType = type || "text";
    return {
      key: "",
      label: "",
      type: resolvedType,
      required: false,
      readonly: false,
      help_text: "",
      placeholder: "",
      prefill: "",
      default: resolvedType === "number" ? 0 : "",
      min: resolvedType === "number" ? 0 : "",
      step: resolvedType === "number" ? 1 : "",
      options: CHOICE_TYPES.has(resolvedType) ? ["Opcao 1", "Opcao 2"] : [],
    };
  }

  function defaultSection() {
    return {
      title: "",
      description: "",
      fields: [defaultField("text")],
    };
  }

  function valueOrEmpty(value) {
    if (value === null || value === undefined) return "";
    return value;
  }

  function parseMaybeNumber(value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return "";
    const normalized = text.replace(",", ".");
    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : text;
  }

  function sanitizeField(rawField) {
    const type = SUPPORTED_FIELD_TYPES.some((item) => item.value === rawField?.type)
      ? rawField.type
      : "text";
    const field = {
      key: String(rawField?.key || "").trim(),
      label: String(rawField?.label || "").trim(),
      type: type,
      required: Boolean(rawField?.required),
      readonly: Boolean(rawField?.readonly),
    };

    const helpText = String(rawField?.help_text || "").trim();
    const placeholder = String(rawField?.placeholder || "").trim();
    const prefill = String(rawField?.prefill || "").trim();
    const defaultValue = valueOrEmpty(rawField?.default);
    const min = valueOrEmpty(rawField?.min);
    const step = valueOrEmpty(rawField?.step);

    if (helpText) field.help_text = helpText;
    if (placeholder) field.placeholder = placeholder;
    if (prefill) field.prefill = prefill;
    if (defaultValue !== "") field.default = type === "number" ? parseMaybeNumber(defaultValue) : defaultValue;
    if (min !== "") field.min = parseMaybeNumber(min);
    if (step !== "") field.step = parseMaybeNumber(step);

    if (CHOICE_TYPES.has(type)) {
      const options = Array.isArray(rawField?.options)
        ? rawField.options.map((option) => String(option || "").trim()).filter(Boolean)
        : [];
      field.options = options.length ? options : ["Opcao 1", "Opcao 2"];
    }

    return field;
  }

  function sanitizeSchema(rawSchema) {
    const schema = {
      title: String(rawSchema?.title || "").trim(),
      subtitle: String(rawSchema?.subtitle || "").trim(),
      submit_label: String(rawSchema?.submit_label || "").trim(),
      sections: [],
    };

    if (Array.isArray(rawSchema?.sections)) {
      schema.sections = rawSchema.sections
        .filter((section) => section && typeof section === "object")
        .map((section) => ({
          title: String(section.title || "").trim(),
          description: String(section.description || "").trim(),
          fields: Array.isArray(section.fields)
            ? section.fields
                .filter((field) => field && typeof field === "object")
                .map((field) => sanitizeField(field))
            : [],
        }));
    }

    if (!schema.sections.length) {
      schema.sections = [defaultSection()];
    }

    return schema;
  }

  function serializeState() {
    const schema = {
      title: String(state.title || "").trim(),
      subtitle: String(state.subtitle || "").trim(),
      submit_label: String(state.submit_label || "").trim(),
      sections: state.sections.map((section) => ({
        title: String(section.title || "").trim(),
        description: String(section.description || "").trim(),
        fields: section.fields.map((field) => {
          const normalized = {
            key: String(field.key || "").trim(),
            label: String(field.label || "").trim(),
            type: field.type || "text",
            required: Boolean(field.required),
          };
          if (field.readonly) normalized.readonly = true;

          const helpText = String(field.help_text || "").trim();
          const placeholder = String(field.placeholder || "").trim();
          const prefill = String(field.prefill || "").trim();
          const defaultValue = valueOrEmpty(field.default);
          const min = valueOrEmpty(field.min);
          const step = valueOrEmpty(field.step);

          if (helpText) normalized.help_text = helpText;
          if (placeholder) normalized.placeholder = placeholder;
          if (prefill) normalized.prefill = prefill;
          if (defaultValue !== "") normalized.default = field.type === "number" ? parseMaybeNumber(defaultValue) : defaultValue;
          if (min !== "") normalized.min = parseMaybeNumber(min);
          if (step !== "") normalized.step = parseMaybeNumber(step);

          if (CHOICE_TYPES.has(field.type)) {
            normalized.options = (field.options || [])
              .map((option) => String(option || "").trim())
              .filter(Boolean);
          }

          return normalized;
        }),
      })),
    };

    return JSON.stringify(schema, null, 2);
  }

  function clearAlert() {
    alertBox.textContent = "";
    alertBox.classList.add("d-none");
  }

  function showAlert(message) {
    alertBox.textContent = message;
    alertBox.classList.remove("d-none");
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fieldTypeOptions(selected) {
    return SUPPORTED_FIELD_TYPES.map((item) =>
      '<option value="' + item.value + '"' + (selected === item.value ? " selected" : "") + ">" + item.label + "</option>"
    ).join("");
  }

  function renderOptions(sectionIndex, fieldIndex, field) {
    if (!CHOICE_TYPES.has(field.type)) return "";

    const rows = (field.options || []).map((option, optionIndex) =>
      '<div class="row g-2 align-items-center mb-2">' +
        '<div class="col">' +
          '<input type="text" class="form-control" value="' + escapeHtml(option) + '"' +
            ' data-role="field-option"' +
            ' data-section-index="' + sectionIndex + '"' +
            ' data-field-index="' + fieldIndex + '"' +
            ' data-option-index="' + optionIndex + '"' +
            ' placeholder="Texto da opcao">' +
        "</div>" +
        '<div class="col-auto">' +
          '<button type="button" class="btn btn-outline-danger"' +
            ' data-action="remove-option"' +
            ' data-section-index="' + sectionIndex + '"' +
            ' data-field-index="' + fieldIndex + '"' +
            ' data-option-index="' + optionIndex + '">' +
            '<i class="fas fa-times"></i>' +
          "</button>" +
        "</div>" +
      "</div>"
    ).join("");

    return (
      '<div class="mt-3">' +
        '<label class="form-label fw-semibold">Opcoes de resposta</label>' +
        rows +
        '<button type="button" class="btn btn-outline-secondary btn-sm mt-1"' +
          ' data-action="add-option"' +
          ' data-section-index="' + sectionIndex + '"' +
          ' data-field-index="' + fieldIndex + '">' +
          '<i class="fas fa-plus me-1"></i>Adicionar opcao' +
        "</button>" +
      "</div>"
    );
  }

  function renderField(sectionIndex, field, fieldIndex) {
    const isNumber = field.type === "number";
    return (
      '<div class="schema-field-card">' +
        '<div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">' +
          "<div>" +
            '<div class="fw-semibold">Pergunta ' + (fieldIndex + 1) + "</div>" +
            '<div class="small text-muted">' + escapeHtml(field.label || "Pergunta sem titulo") + "</div>" +
          "</div>" +
          '<div class="schema-controls d-flex flex-wrap gap-2">' +
            renderActionButton("move-field-up", sectionIndex, fieldIndex, "secondary", "arrow-up") +
            renderActionButton("move-field-down", sectionIndex, fieldIndex, "secondary", "arrow-down") +
            renderActionButton("duplicate-field", sectionIndex, fieldIndex, "secondary", "copy") +
            renderActionButton("remove-field", sectionIndex, fieldIndex, "danger", "trash") +
          "</div>" +
        "</div>" +
        '<div class="row g-3">' +
          '<div class="col-12">' +
            '<label class="form-label fw-semibold">Pergunta</label>' +
            renderTextInput(sectionIndex, fieldIndex, "label", field.label, "Ex.: Como voce esta se sentindo hoje?") +
          "</div>" +
          '<div class="col-md-4">' +
            '<label class="form-label fw-semibold">Chave interna</label>' +
            renderTextInput(sectionIndex, fieldIndex, "key", field.key, "ex.: classificacao_melhora", " font-monospace") +
          "</div>" +
          '<div class="col-md-4">' +
            '<label class="form-label fw-semibold">Tipo</label>' +
            '<select class="form-select" data-role="field-prop" data-section-index="' + sectionIndex + '" data-field-index="' + fieldIndex + '" data-prop="type">' +
              fieldTypeOptions(field.type) +
            "</select>" +
          "</div>" +
          '<div class="col-md-4 d-flex align-items-end">' +
            '<div class="d-grid gap-2 mb-2">' +
              '<div class="form-check">' +
                '<input class="form-check-input" type="checkbox" id="required-' + sectionIndex + "-" + fieldIndex + '"' +
                  (field.required ? " checked" : "") +
                  ' data-role="field-prop" data-section-index="' + sectionIndex + '" data-field-index="' + fieldIndex + '" data-prop="required">' +
                '<label class="form-check-label" for="required-' + sectionIndex + "-" + fieldIndex + '">Pergunta obrigatoria</label>' +
              "</div>" +
              '<div class="form-check">' +
                '<input class="form-check-input" type="checkbox" id="readonly-' + sectionIndex + "-" + fieldIndex + '"' +
                  (field.readonly ? " checked" : "") +
                  ' data-role="field-prop" data-section-index="' + sectionIndex + '" data-field-index="' + fieldIndex + '" data-prop="readonly">' +
                '<label class="form-check-label" for="readonly-' + sectionIndex + "-" + fieldIndex + '">Somente leitura</label>' +
              "</div>" +
            "</div>" +
          "</div>" +
          '<div class="col-12">' +
            '<label class="form-label fw-semibold">Ajuda abaixo da pergunta</label>' +
            renderTextarea(sectionIndex, fieldIndex, "help_text", field.help_text, "Texto opcional para orientar o paciente", 2) +
          "</div>" +
          '<div class="col-md-4">' +
            '<label class="form-label fw-semibold">Placeholder</label>' +
            renderTextInput(sectionIndex, fieldIndex, "placeholder", field.placeholder, "Texto de exemplo") +
          "</div>" +
          '<div class="col-md-4">' +
            '<label class="form-label fw-semibold">Prefill</label>' +
            renderTextInput(sectionIndex, fieldIndex, "prefill", field.prefill, "nome, ficha_sinan, endereco...", " font-monospace") +
          "</div>" +
          '<div class="col-md-4">' +
            '<label class="form-label fw-semibold">Valor padrao</label>' +
            renderGenericInput(sectionIndex, fieldIndex, "default", field.default, isNumber ? "number" : "text", isNumber ? ' step="any"' : "") +
          "</div>" +
          '<div class="col-md-3">' +
            '<label class="form-label fw-semibold">Minimo</label>' +
            renderGenericInput(sectionIndex, fieldIndex, "min", field.min, "number", ' step="any"') +
          "</div>" +
          '<div class="col-md-3">' +
            '<label class="form-label fw-semibold">Passo</label>' +
            renderGenericInput(sectionIndex, fieldIndex, "step", field.step, "number", ' step="any"') +
          "</div>" +
        "</div>" +
        renderOptions(sectionIndex, fieldIndex, field) +
      "</div>"
    );
  }

  function renderSection(section, sectionIndex) {
    const fieldsHtml = section.fields.length
      ? section.fields.map((field, fieldIndex) => renderField(sectionIndex, field, fieldIndex)).join("")
      : '<div class="schema-empty-state"><div class="fw-semibold mb-1">Nenhuma pergunta nesta secao</div><div class="small">Use o botao "Adicionar pergunta" para comecar.</div></div>';

    return (
      '<section class="schema-section-card">' +
        '<div class="schema-section-head">' +
          '<div class="d-flex flex-wrap align-items-center justify-content-between gap-2">' +
            "<div>" +
              '<div class="fw-semibold fs-5">Secao ' + (sectionIndex + 1) + "</div>" +
              '<div class="small text-muted">' + escapeHtml(section.title || "Sem titulo") + "</div>" +
            "</div>" +
            '<div class="schema-controls d-flex flex-wrap gap-2">' +
              renderSectionActionButton("move-section-up", sectionIndex, "secondary", "arrow-up") +
              renderSectionActionButton("move-section-down", sectionIndex, "secondary", "arrow-down") +
              renderSectionActionButton("duplicate-section", sectionIndex, "secondary", "copy") +
              renderSectionActionButton("remove-section", sectionIndex, "danger", "trash") +
            "</div>" +
          "</div>" +
        "</div>" +
        '<div class="p-3">' +
          '<div class="row g-3">' +
            '<div class="col-md-6">' +
              '<label class="form-label fw-semibold">Titulo da secao</label>' +
              '<input type="text" class="form-control" value="' + escapeHtml(section.title) + '"' +
                ' data-role="section-prop" data-section-index="' + sectionIndex + '" data-prop="title" placeholder="Ex.: Secao 1: Evolucao da saude">' +
            "</div>" +
            '<div class="col-md-6">' +
              '<label class="form-label fw-semibold">Descricao</label>' +
              '<textarea class="form-control" rows="2"' +
                ' data-role="section-prop" data-section-index="' + sectionIndex + '" data-prop="description" placeholder="Explique rapidamente o objetivo desta secao">' +
                escapeHtml(section.description) +
              "</textarea>" +
            "</div>" +
          "</div>" +
          '<div class="d-flex flex-wrap gap-2 mt-3 mb-3">' +
            '<button type="button" class="btn btn-outline-primary btn-sm" data-action="add-field" data-section-index="' + sectionIndex + '">' +
              '<i class="fas fa-plus me-1"></i>Adicionar pergunta' +
            "</button>" +
            '<button type="button" class="btn btn-outline-secondary btn-sm" data-action="add-radio-field" data-section-index="' + sectionIndex + '">' +
              '<i class="far fa-dot-circle me-1"></i>Multipla escolha' +
            "</button>" +
            '<button type="button" class="btn btn-outline-secondary btn-sm" data-action="add-checkbox-field" data-section-index="' + sectionIndex + '">' +
              '<i class="far fa-check-square me-1"></i>Caixas de selecao' +
            "</button>" +
          "</div>" +
          '<div class="d-grid gap-3">' + fieldsHtml + "</div>" +
        "</div>" +
      "</section>"
    );
  }

  function renderActionButton(action, sectionIndex, fieldIndex, tone, icon) {
    return (
      '<button type="button" class="btn btn-outline-' + tone + '"' +
        ' data-action="' + action + '"' +
        ' data-section-index="' + sectionIndex + '"' +
        ' data-field-index="' + fieldIndex + '">' +
        '<i class="fas fa-' + icon + '"></i>' +
      "</button>"
    );
  }

  function renderSectionActionButton(action, sectionIndex, tone, icon) {
    return (
      '<button type="button" class="btn btn-outline-' + tone + '"' +
        ' data-action="' + action + '"' +
        ' data-section-index="' + sectionIndex + '">' +
        '<i class="fas fa-' + icon + '"></i>' +
      "</button>"
    );
  }

  function renderTextInput(sectionIndex, fieldIndex, prop, value, placeholder, extraClass) {
    return (
      '<input type="text" class="form-control' + (extraClass || "") + '"' +
        ' value="' + escapeHtml(value || "") + '"' +
        ' data-role="field-prop"' +
        ' data-section-index="' + sectionIndex + '"' +
        ' data-field-index="' + fieldIndex + '"' +
        ' data-prop="' + prop + '"' +
        ' placeholder="' + escapeHtml(placeholder || "") + '">'
    );
  }

  function renderGenericInput(sectionIndex, fieldIndex, prop, value, type, extraAttrs) {
    return (
      '<input type="' + type + '" class="form-control"' +
        ' value="' + escapeHtml(valueOrEmpty(value)) + '"' +
        ' data-role="field-prop"' +
        ' data-section-index="' + sectionIndex + '"' +
        ' data-field-index="' + fieldIndex + '"' +
        ' data-prop="' + prop + '"' +
        (extraAttrs || "") +
      ">"
    );
  }

  function renderTextarea(sectionIndex, fieldIndex, prop, value, placeholder, rows) {
    return (
      '<textarea class="form-control" rows="' + rows + '"' +
        ' data-role="field-prop"' +
        ' data-section-index="' + sectionIndex + '"' +
        ' data-field-index="' + fieldIndex + '"' +
        ' data-prop="' + prop + '"' +
        ' placeholder="' + escapeHtml(placeholder || "") + '">' +
        escapeHtml(value || "") +
      "</textarea>"
    );
  }

  function updateSummary() {
    const totalFields = state.sections.reduce((sum, section) => sum + section.fields.length, 0);
    document.getElementById("schemaSummaryTitle").textContent = state.title || "-";
    document.getElementById("schemaSummarySections").textContent = state.sections.length;
    document.getElementById("schemaSummaryFields").textContent = totalFields;
  }

  function render(syncRaw) {
    titleInput.value = state.title || "";
    subtitleInput.value = state.subtitle || "";
    submitLabelInput.value = state.submit_label || "";
    sectionsContainer.innerHTML = state.sections.map((section, sectionIndex) => renderSection(section, sectionIndex)).join("");
    if (syncRaw) {
      rawTextarea.value = serializeState();
    }
    updateSummary();
    clearAlert();
  }

  function getField(sectionIndex, fieldIndex) {
    const section = state.sections[sectionIndex];
    return section && section.fields ? section.fields[fieldIndex] : null;
  }

  function cloneValue(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function moveItem(list, index, direction) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= list.length) return;
    const current = list[index];
    list[index] = list[targetIndex];
    list[targetIndex] = current;
  }

  titleInput.addEventListener("input", function () {
    state.title = titleInput.value;
    updateSummary();
  });

  subtitleInput.addEventListener("input", function () {
    state.subtitle = subtitleInput.value;
  });

  submitLabelInput.addEventListener("input", function () {
    state.submit_label = submitLabelInput.value;
  });

  sectionsContainer.addEventListener("input", function (event) {
    const target = event.target;
    const sectionIndex = Number(target.dataset.sectionIndex);
    const fieldIndex = Number(target.dataset.fieldIndex);
    const prop = target.dataset.prop;

    if (target.dataset.role === "section-prop") {
      if (!Number.isNaN(sectionIndex) && prop) {
        state.sections[sectionIndex][prop] = target.value;
        updateSummary();
      }
      return;
    }

    if (target.dataset.role === "field-prop") {
      const field = getField(sectionIndex, fieldIndex);
      if (!field || !prop) return;
      field[prop] = target.type === "checkbox" ? target.checked : target.value;
      return;
    }

    if (target.dataset.role === "field-option") {
      const field = getField(sectionIndex, fieldIndex);
      const optionIndex = Number(target.dataset.optionIndex);
      if (!field || Number.isNaN(optionIndex)) return;
      field.options[optionIndex] = target.value;
    }
  });

  sectionsContainer.addEventListener("change", function (event) {
    const target = event.target;
    if (target.dataset.role !== "field-prop" || target.dataset.prop !== "type") return;
    const sectionIndex = Number(target.dataset.sectionIndex);
    const fieldIndex = Number(target.dataset.fieldIndex);
    const field = getField(sectionIndex, fieldIndex);
    if (!field) return;
    field.type = target.value;
    if (CHOICE_TYPES.has(field.type) && (!Array.isArray(field.options) || !field.options.length)) {
      field.options = ["Opcao 1", "Opcao 2"];
    }
    if (!CHOICE_TYPES.has(field.type)) {
      delete field.options;
    }
    render();
  });

  sectionsContainer.addEventListener("click", function (event) {
    const button = event.target.closest("[data-action]");
    if (!button) return;

    const action = button.dataset.action;
    const sectionIndex = Number(button.dataset.sectionIndex);
    const fieldIndex = Number(button.dataset.fieldIndex);
    const optionIndex = Number(button.dataset.optionIndex);

    if (action === "add-field") {
      state.sections[sectionIndex].fields.push(defaultField("text"));
      render();
      return;
    }

    if (action === "add-radio-field") {
      state.sections[sectionIndex].fields.push(defaultField("radio"));
      render();
      return;
    }

    if (action === "add-checkbox-field") {
      state.sections[sectionIndex].fields.push(defaultField("checkboxes"));
      render();
      return;
    }

    if (action === "remove-field") {
      state.sections[sectionIndex].fields.splice(fieldIndex, 1);
      render();
      return;
    }

    if (action === "duplicate-field") {
      const field = getField(sectionIndex, fieldIndex);
      if (!field) return;
      state.sections[sectionIndex].fields.splice(fieldIndex + 1, 0, cloneValue(field));
      render();
      return;
    }

    if (action === "move-field-up") {
      moveItem(state.sections[sectionIndex].fields, fieldIndex, -1);
      render();
      return;
    }

    if (action === "move-field-down") {
      moveItem(state.sections[sectionIndex].fields, fieldIndex, 1);
      render();
      return;
    }

    if (action === "add-option") {
      const field = getField(sectionIndex, fieldIndex);
      if (!field) return;
      field.options = Array.isArray(field.options) ? field.options : [];
      field.options.push("Opcao " + (field.options.length + 1));
      render();
      return;
    }

    if (action === "remove-option") {
      const field = getField(sectionIndex, fieldIndex);
      if (!field || !Array.isArray(field.options)) return;
      field.options.splice(optionIndex, 1);
      render();
      return;
    }

    if (action === "remove-section") {
      state.sections.splice(sectionIndex, 1);
      if (!state.sections.length) state.sections.push(defaultSection());
      render();
      return;
    }

    if (action === "duplicate-section") {
      state.sections.splice(sectionIndex + 1, 0, cloneValue(state.sections[sectionIndex]));
      render();
      return;
    }

    if (action === "move-section-up") {
      moveItem(state.sections, sectionIndex, -1);
      render();
      return;
    }

    if (action === "move-section-down") {
      moveItem(state.sections, sectionIndex, 1);
      render();
    }
  });

  document.getElementById("addSectionBtn").addEventListener("click", function () {
    state.sections.push(defaultSection());
    render();
  });

  document.getElementById("refreshJsonBtn").addEventListener("click", function () {
    rawTextarea.value = serializeState();
    clearAlert();
  });

  document.getElementById("copyFromEditorBtn").addEventListener("click", function () {
    rawTextarea.value = serializeState();
    clearAlert();
  });

  document.getElementById("applyRawJsonBtn").addEventListener("click", function () {
    try {
      state = sanitizeSchema(JSON.parse(rawTextarea.value || "{}"));
      render(true);
    } catch (error) {
      showAlert("Nao consegui ler esse JSON agora. Revise o texto e tente novamente. (" + error.message + ")");
    }
  });

  form.addEventListener("submit", function (event) {
    try {
      const serialized = serializeState();
      hiddenInput.value = serialized;
      rawTextarea.value = serialized;
      clearAlert();
    } catch (error) {
      event.preventDefault();
      showAlert("Nao foi possivel preparar o formulario para salvar. " + error.message);
    }
  });

  render(false);
})();
