const JSON_HEADERS = {
  Accept: 'application/json',
  'Content-Type': 'application/json'
};

const DEFAULT_ERROR_MESSAGE = 'Erro ao salvar. Verifique os dados e tente novamente.';
const DEFAULT_SUCCESS_MESSAGE = 'Agendamento atualizado com sucesso.';

function buildHeaders(csrfToken = '', extraHeaders = {}) {
  const headers = { ...JSON_HEADERS, ...extraHeaders };
  if (csrfToken) {
    headers['X-CSRFToken'] = csrfToken;
  }
  return headers;
}

function buildUrlSearchParams(params = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return;
    }
    searchParams.set(key, value);
  });
  return searchParams;
}

export async function fetchAvailableTimes(veterinarioId, date, options = {}) {
  if (!veterinarioId || !date) {
    return [];
  }
  const {
    kind,
    searchParams = {},
    fetchOptions = {},
    basePath = '/api/specialist'
  } = options;
  const params = buildUrlSearchParams({ ...searchParams, date, kind });
  const query = params.toString();
  const endpointBase = basePath.endsWith('/') ? basePath.slice(0, -1) : basePath;
  const endpoint = `${endpointBase}/${veterinarioId}/available_times${query ? `?${query}` : ''}`;
  try {
    const response = await fetch(endpoint, fetchOptions);
    if (!response.ok) {
      return [];
    }
    const data = await response.json();
    return Array.isArray(data) ? data : [];
  } catch (error) {
    console.error('Erro ao buscar horários disponíveis', error);
    return [];
  }
}

export async function submitAppointmentUpdate(url, payload, csrfToken = '', options = {}) {
  const {
    defaultErrorMessage = DEFAULT_ERROR_MESSAGE,
    successMessage = DEFAULT_SUCCESS_MESSAGE,
    fetchOptions = {}
  } = options;
  const requestInit = {
    method: 'POST',
    ...fetchOptions,
    headers: buildHeaders(csrfToken, fetchOptions.headers || {}),
    body: JSON.stringify(payload ?? {})
  };
  try {
    const response = await fetch(url, requestInit);
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (response.ok && data && data.success) {
      return {
        success: true,
        data,
        message: data.message || successMessage,
        response
      };
    }
    const message = (data && data.message) ? data.message : defaultErrorMessage;
    return {
      success: false,
      data,
      message,
      response
    };
  } catch (error) {
    console.error('Erro ao enviar atualização de agendamento', error);
    return {
      success: false,
      data: null,
      message: defaultErrorMessage,
      response: null
    };
  }
}

if (typeof window !== 'undefined') {
  window.AppointmentsShared = {
    ...(window.AppointmentsShared || {}),
    fetchAvailableTimes,
    submitAppointmentUpdate
  };
}
