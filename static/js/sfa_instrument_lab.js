(function () {
  'use strict';

  const root = document.getElementById('sfa-instrument-lab');
  if (!root) return;

  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
  const percent = (value, total) => total > 0 ? Math.round((value / total) * 100) : 0;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const COHORT_SIZE = 100;

  function question(id, label, type, options, extra) {
    return Object.assign({
      id,
      label,
      type,
      options: options || [],
      required: true,
      seconds: type === 'checkboxes' ? 18 : (type === 'textarea' ? 22 : 12)
    }, extra || {});
  }

  const noCurrentDanger = 'Nenhum destes sinais agora';

  const stages = {
    t0: {
      label: 'T0',
      purpose: 'Reconhecer vínculos de pessoa, tempo, lugar e exposição sem repetir o SINAN.',
      summary: [
        'Localiza outra pessoa doente e o possível vínculo em comum.',
        'Mantém alimento, água, animais e ambiente com detalhe acionável.',
        'Registra o diagnóstico que a pessoa entendeu para comparação posterior.',
        'Mede apenas a carga funcional e econômica essencial.'
      ],
      imported: ['identificação', 'endereço e bairro', 'início dos sintomas', 'sinais do SINAN', 'comorbidades', 'hospitalização', 'exames e resultados'],
      sections: [
        {
          title: 'Participação', icon: 'fa-signature', questions: [
            question('respondent_role', 'Quem está respondendo?', 'radio', ['A própria pessoa', 'Pai, mãe ou responsável', 'Outra pessoa autorizada']),
            question('respondent_name', 'Nome e relação de quem responde', 'text', [], {
              conditional: true,
              showWhen: (a) => a.respondent_role && a.respondent_role !== 'A própria pessoa',
              placeholder: 'Ex.: Maria Martins, mãe'
            }),
            question('consent', 'Consentimento para participar', 'checkboxes', ['Li o TCLE e aceito participar voluntariamente.'], { seconds: 10 })
          ]
        },
        {
          title: 'Possível vínculo coletivo', icon: 'fa-people-group', questions: [
            question('similar_cases', 'Você soube de outra pessoa com febre ou sintomas parecidos perto da mesma época?', 'radio', ['Não', 'Sim', 'Não sei']),
            question('shared_setting', 'O que essas pessoas podem ter compartilhado?', 'checkboxes', [
              'Casa', 'Vizinhança', 'Trabalho', 'Escola', 'Serviço de saúde', 'Refeição ou alimento',
              'Evento', 'Viagem ou transporte', 'Atividade com animais', 'Outro'
            ], { conditional: true, showWhen: (a) => a.similar_cases === 'Sim' }),
            question('cluster_timing', 'Os sintomas das outras pessoas começaram quando?', 'radio', ['Antes dos seus', 'Na mesma época', 'Depois dos seus', 'Não sei'], {
              conditional: true, showWhen: (a) => a.similar_cases === 'Sim'
            })
          ]
        },
        {
          title: 'Ambiente e deslocamentos', icon: 'fa-tree', questions: [
            question('environment', 'Nos 15 dias antes dos sintomas, houve alguma destas situações?', 'checkboxes', [
              'Água suja, lama, enchente ou esgoto', 'Rio, córrego, pesca ou natação', 'Mata, trilha, pasto ou camping',
              'Chácara, fazenda ou área rural', 'Muitos mosquitos, carrapatos ou outros vetores',
              'Viagem ou permanência em outro município', 'Nenhuma destas situações'
            ], { exclusive: ['Nenhuma destas situações'] })
          ]
        },
        {
          title: 'Animais e interface One Health', icon: 'fa-paw', questions: [
            question('animal', 'Houve algum evento animal incomum ou contato de risco?', 'checkboxes', [
              'Animal doente ou com comportamento incomum', 'Morte ou desaparecimento de animal',
              'Aborto, parto ou contato com placenta', 'Urina, fezes, sangue ou carcaça',
              'Mordida ou arranhadura', 'Carrapato', 'Trabalho ou atividade com animais',
              'Outro evento relevante', 'Nenhum evento animal relevante'
            ], {
              help: 'Contato rotineiro com cão ou gato saudável, sozinho, não precisa ser marcado.',
              exclusive: ['Nenhum evento animal relevante']
            }),
            question('animal_detail', 'Qual animal e qual evento ocorreu?', 'textarea', [], {
              conditional: true,
              showWhen: (a) => hasPositiveSelection(a.animal, 'Nenhum evento animal relevante'),
              placeholder: 'Ex.: cães da propriedade com doença incomum; retirada de carrapato'
            })
          ]
        },
        {
          title: 'Alimentos, água e produtos', icon: 'fa-bowl-food', questions: [
            question('food', 'Houve alguma destas exposições nos 15 dias anteriores?', 'checkboxes', [
              'Carne crua ou malpassada, caça ou abate', 'Leite cru ou queijo sem inspeção', 'Ovo cru ou malcozido',
              'Água sem tratamento', 'Refeição em evento, estabelecimento ou ambulante',
              'Alimento ou produto com aspecto suspeito', 'Outras pessoas que consumiram também adoeceram',
              'Nenhuma destas exposições'
            ], { exclusive: ['Nenhuma destas exposições'] })
          ]
        },
        {
          title: 'Detalhe mínimo para verificar a pista', icon: 'fa-location-crosshairs', questions: [
            question('exposure_specific', 'O que exatamente pode ter sido compartilhado?', 'text', [], {
              conditional: true, showWhen: hasT0CollectiveDoor,
              placeholder: 'Alimento, produto, água, animal, local, atividade ou evento específico'
            }),
            question('exposure_source', 'Qual foi a fonte, marca, estabelecimento ou local?', 'text', [], {
              conditional: true, showWhen: hasT0CollectiveDoor,
              placeholder: 'Nome que permita localizar e verificar a pista'
            }),
            question('exposure_period', 'Qual foi a data ou o período aproximado da exposição?', 'text', [], {
              conditional: true, showWhen: hasT0CollectiveDoor,
              placeholder: 'Ex.: almoço de 21/08; entre 18 e 20/08'
            }),
            question('exposed_count', 'Quantas pessoas podem ter sido expostas?', 'number', [], {
              conditional: true, showWhen: hasT0CollectiveDoor, min: 1, max: 999,
              help: 'Informe uma estimativa; essa contagem não identifica pessoas únicas.'
            }),
            question('sick_count', 'Entre elas, quantas pessoas adoeceram?', 'number', [], {
              conditional: true, showWhen: hasT0CollectiveDoor, min: 1, max: 999,
              help: 'Inclua você; relatos serão mantidos separados dos participantes diretamente observados.'
            }),
            question('source_active_t0', 'A possível fonte ou situação ainda existe?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true, showWhen: hasT0CollectiveDoor
            }),
            question('others_still_exposed_t0', 'Outras pessoas ainda podem estar expostas?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true, showWhen: hasT0CollectiveDoor
            })
          ]
        },
        {
          title: 'Complemento clínico e comunicação', icon: 'fa-stethoscope', questions: [
            question('extra_symptoms', 'Além do que já está no SINAN, houve algum destes sintomas?', 'checkboxes', [
              'Diarreia', 'Tosse, coriza ou dor de garganta', 'Olhos ou pele amarelados', 'Urina escura',
              'Lesão de pele incomum', 'Outro sintoma relevante', 'Nenhum destes sintomas'
            ], { exclusive: ['Nenhum destes sintomas'] }),
            question('understood_diagnosis', 'Qual diagnóstico ou suspeita você entendeu que recebeu?', 'radio', [
              'Nenhum diagnóstico ou suspeita', 'Dengue', 'Chikungunya', 'Zika',
              'Virose ou síndrome viral indefinida', 'Outro', 'Exames pendentes', 'Não entendi ou não lembro'
            ]),
            question('diagnosis_other', 'Qual outro diagnóstico ou suspeita?', 'text', [], {
              conditional: true, showWhen: (a) => a.understood_diagnosis === 'Outro'
            }),
            question('diagnosis_status', 'Essa informação foi apresentada como:', 'radio', ['Suspeita', 'Confirmação', 'Não sei'], {
              conditional: true,
              showWhen: (a) => ['Dengue', 'Chikungunya', 'Zika', 'Virose ou síndrome viral indefinida', 'Outro'].includes(a.understood_diagnosis)
            }),
            question('safety', 'Você apresenta agora algum sinal que exige nova avaliação?', 'checkboxes', [
              'Falta de ar importante', 'Desmaio ou confusão', 'Sangramento importante',
              'Piora intensa ou preocupação urgente', noCurrentDanger
            ], { exclusive: [noCurrentDanger], safety: true })
          ]
        },
        {
          title: 'Carga essencial e observação aberta', icon: 'fa-briefcase-medical', questions: [
            question('days_unable', 'Por quantos dias você ficou completamente sem conseguir realizar suas atividades habituais?', 'number', [], { min: 0, max: 60 }),
            question('expense_any', 'Houve algum gasto da família por causa deste episódio?', 'radio', ['Não', 'Sim']),
            question('expense_total', 'Valor total aproximado até agora (R$)', 'number', [], {
              conditional: true, showWhen: (a) => a.expense_any === 'Sim', min: 0, max: 99999, step: '0.01'
            }),
            question('caregiver_stop', 'Outra pessoa deixou suas atividades para cuidar de você?', 'radio', ['Não', 'Sim']),
            question('caregiver_days', 'Por aproximadamente quantos dias?', 'number', [], {
              conditional: true, showWhen: (a) => a.caregiver_stop === 'Sim', min: 0, max: 60
            }),
            question('open_exposure', 'Existe algum alimento, produto, animal, lugar, atividade ou evento suspeito que não perguntamos?', 'textarea', [], {
              required: false, placeholder: 'Opcional'
            })
          ]
        }
      ]
    },
    t10: {
      label: 'T10',
      purpose: 'Descobrir se o caso isolado virou um sinal coletivo e se a possível fonte continua ativa.',
      summary: [
        'Atualiza novos casos e novas pistas de exposição.',
        'Pergunta se a fonte ainda existe e se outras pessoas permanecem expostas.',
        'Captura mudança do diagnóstico entendido sem repetir toda a história clínica.',
        'Acrescenta apenas dias e gastos ocorridos desde o T0.'
      ],
      imported: ['nome e contato', 'respostas do T0', 'atendimentos municipais', 'internação', 'resultados disponíveis'],
      sections: [
        {
          title: 'Evolução e segurança', icon: 'fa-heart-pulse', questions: [
            question('trajectory', 'Como você está desde o T0?', 'radio', ['Recuperado', 'Melhorando', 'Sem mudança', 'Piorando', 'Melhorei e depois piorei']),
            question('main_symptom', 'Qual é o principal problema hoje?', 'text', [], {
              conditional: true, showWhen: (a) => a.trajectory && a.trajectory !== 'Recuperado', required: false
            }),
            question('safety', 'Você apresenta agora algum sinal que exige nova avaliação?', 'checkboxes', [
              'Falta de ar importante', 'Desmaio ou confusão', 'Sangramento importante',
              'Piora intensa ou preocupação urgente', noCurrentDanger
            ], { exclusive: [noCurrentDanger], safety: true }),
            question('returned_care', 'Desde o T0, houve atendimento fora da rede municipal de Orlândia ou algum atendimento que possa não estar no prontuário?', 'radio', ['Não', 'Sim'])
          ]
        },
        {
          title: 'Atualização diagnóstica', icon: 'fa-file-medical', questions: [
            question('diagnosis_update', 'Depois do T0, recebeu alguma informação nova sobre o diagnóstico?', 'radio', [
              'Sem mudança', 'O diagnóstico anterior foi confirmado', 'O diagnóstico anterior foi descartado',
              'Recebi outro diagnóstico ou suspeita', 'Exames ainda pendentes',
              'Recebi resultado, mas não entendi', 'Não recebi informação'
            ], {
              labelFor: () => {
                const previous = state.answers.t0.understood_diagnosis;
                return previous
                  ? `No T0 você relatou “${previous}”. Depois disso, recebeu alguma informação nova?`
                  : 'Depois do T0, recebeu alguma informação nova sobre o diagnóstico?';
              }
            }),
            question('diagnosis_now', 'Qual diagnóstico ou suspeita foi informado agora?', 'radio', [
              'Dengue', 'Chikungunya', 'Zika', 'Virose ou síndrome viral indefinida', 'Outro'
            ], {
              conditional: true,
              showWhen: (a) => ['O diagnóstico anterior foi confirmado', 'Recebi outro diagnóstico ou suspeita'].includes(a.diagnosis_update)
            }),
            question('diagnosis_other', 'Qual outro diagnóstico ou suspeita?', 'text', [], {
              conditional: true, showWhen: (a) => a.diagnosis_now === 'Outro'
            })
          ]
        },
        {
          title: 'Novos vínculos e permanência da fonte', icon: 'fa-magnifying-glass-location', questions: [
            question('new_similar', 'Depois do T0, você soube de outra pessoa com sintomas parecidos?', 'radio', ['Não', 'Sim', 'Não sei']),
            question('new_similar_detail', 'Quantas pessoas, onde e quando adoeceram?', 'textarea', [], {
              conditional: true, showWhen: (a) => a.new_similar === 'Sim',
              placeholder: 'Número aproximado + local + data/período'
            }),
            question('new_common_exposure', 'Qual exposição em comum passou a ser suspeita?', 'text', [], {
              conditional: true, showWhen: (a) => a.new_similar === 'Sim'
            }),
            question('new_exposure_info', 'Surgiu alguma nova pista sobre alimento, produto, água, animal, lugar, trabalho, evento ou atividade?', 'radio', ['Não', 'Sim']),
            question('new_exposure_detail', 'Qual foi a nova pista?', 'textarea', [], {
              conditional: true, showWhen: (a) => a.new_exposure_info === 'Sim'
            }),
            question('source_active', 'A possível fonte ou situação ainda existe?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true,
              showWhen: (a) => a.new_similar === 'Sim' || a.new_exposure_info === 'Sim' || priorT0ExposureMentioned()
            }),
            question('others_exposed', 'Outras pessoas ainda podem estar expostas?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true,
              showWhen: (a) => a.new_similar === 'Sim' || a.new_exposure_info === 'Sim' || priorT0ExposureMentioned()
            })
          ]
        },
        {
          title: 'Carga adicional desde o T0', icon: 'fa-calendar-plus', questions: [
            question('additional_days', 'Quantos dias adicionais você ficou completamente sem suas atividades desde o T0?', 'number', [], { min: 0, max: 30 }),
            question('additional_expense_any', 'Houve novos gastos desde o T0?', 'radio', ['Não', 'Sim']),
            question('additional_expense', 'Total aproximado dos novos gastos (R$)', 'number', [], {
              conditional: true, showWhen: (a) => a.additional_expense_any === 'Sim', min: 0, max: 99999, step: '0.01'
            }),
            question('lost_income_any', 'Houve perda de renda desde o T0?', 'radio', ['Não', 'Sim'])
          ]
        }
      ]
    },
    t30: {
      label: 'T30',
      purpose: 'Encerrar o possível sinal coletivo: fonte esclarecida, interrompida ou ainda invisível.',
      summary: [
        'Verifica novos casos desde o T10 e informação final sobre a fonte.',
        'Registra orientação ou ação percebida sem atribuir causalidade.',
        'Pergunta se surgiram casos depois da ação apenas de modo descritivo.',
        'Mantém desfecho individual e custo como informação complementar enxuta.'
      ],
      imported: ['nome e contato', 'respostas T0/T10', 'linha diagnóstica', 'atendimentos e exames', 'dias e gastos anteriores'],
      sections: [
        {
          title: 'Encerramento individual e segurança', icon: 'fa-circle-check', questions: [
            question('episode_ended', 'Para você, este episódio de doença terminou?', 'radio', ['Sim', 'Não']),
            question('main_problem', 'Qual é o principal problema que permanece?', 'text', [], {
              conditional: true, showWhen: (a) => a.episode_ended === 'Não', required: false
            }),
            question('safety', 'Você apresenta agora algum sinal que exige nova avaliação?', 'checkboxes', [
              'Falta de ar importante', 'Desmaio ou confusão', 'Sangramento importante',
              'Piora intensa ou preocupação urgente', noCurrentDanger
            ], { exclusive: [noCurrentDanger], safety: true }),
            question('activity_return', 'Como está seu retorno às atividades habituais?', 'radio', ['Retorno completo', 'Retorno parcial', 'Ainda não retornei']),
            question('activity_return_date', 'Data aproximada do retorno completo', 'date', [], {
              conditional: true, showWhen: (a) => a.activity_return === 'Retorno completo', required: false
            })
          ]
        },
        {
          title: 'Informação diagnóstica final', icon: 'fa-notes-medical', questions: [
            question('diagnosis_update', 'Depois do último contato, recebeu nova informação sobre o diagnóstico?', 'radio', [
              'Sem mudança', 'Diagnóstico confirmado', 'Diagnóstico descartado', 'Outro diagnóstico ou suspeita',
              'Exames ainda pendentes', 'Recebi resultado, mas não entendi', 'Não recebi informação'
            ], {
              labelFor: () => {
                const previous = state.answers.t10.diagnosis_now || state.answers.t0.understood_diagnosis;
                return previous
                  ? `No último contato, você relatou “${previous}”. Depois disso, recebeu nova informação?`
                  : 'Depois do último contato, recebeu nova informação sobre o diagnóstico?';
              }
            }),
            question('diagnosis_final', 'Qual diagnóstico ou suspeita você entendeu como final?', 'radio', [
              'Dengue', 'Chikungunya', 'Zika', 'Virose ou síndrome viral indefinida', 'Outro'
            ], {
              conditional: true,
              showWhen: (a) => ['Diagnóstico confirmado', 'Outro diagnóstico ou suspeita'].includes(a.diagnosis_update)
            }),
            question('diagnosis_other', 'Qual outro diagnóstico ou suspeita?', 'text', [], {
              conditional: true, showWhen: (a) => a.diagnosis_final === 'Outro'
            })
          ]
        },
        {
          title: 'Fechamento do possível risco coletivo', icon: 'fa-shield-heart', questions: [
            question('new_similar', 'Desde o último contato concluído, soube de novos casos parecidos?', 'radio', ['Não', 'Sim', 'Não sei']),
            question('new_similar_detail', 'Quantas pessoas, onde e quando adoeceram?', 'textarea', [], {
              conditional: true, showWhen: (a) => a.new_similar === 'Sim'
            }),
            question('source_new_info', 'Surgiu alguma nova informação sobre a possível fonte?', 'radio', ['Não', 'Sim']),
            question('source_new_detail', 'Qual informação surgiu?', 'textarea', [], {
              conditional: true, showWhen: (a) => a.source_new_info === 'Sim'
            }),
            question('source_active', 'A possível fonte ainda existe ou outras pessoas continuam expostas?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true,
              showWhen: (a) => a.new_similar === 'Sim' || a.source_new_info === 'Sim' || priorCollectiveSignalMentioned()
            }),
            question('guidance_action', 'Você ou o grupo exposto recebeu orientação ou percebeu alguma ação da Vigilância?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true,
              showWhen: (a) => a.new_similar === 'Sim' || a.source_new_info === 'Sim' || priorCollectiveSignalMentioned()
            }),
            question('cases_after_action', 'Depois dessa orientação ou ação, você soube de novos casos?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true, showWhen: (a) => a.guidance_action === 'Sim'
            })
          ]
        },
        {
          title: 'Carga adicional desde o T10', icon: 'fa-calendar-check', questions: [
            question('additional_days', 'Quantos dias adicionais ficou completamente sem suas atividades desde o último contato?', 'number', [], { min: 0, max: 30 }),
            question('additional_expense_any', 'Houve novos gastos desde o último contato?', 'radio', ['Não', 'Sim']),
            question('additional_expense', 'Total aproximado dos novos gastos (R$)', 'number', [], {
              conditional: true, showWhen: (a) => a.additional_expense_any === 'Sim', min: 0, max: 99999, step: '0.01'
            }),
            question('lost_income_any', 'Houve nova perda de renda desde o último contato?', 'radio', ['Não', 'Sim'])
          ]
        }
      ]
    }
  };

  const exampleAnswers = {
    t0: {
      respondent_role: 'A própria pessoa',
      consent: ['Li o TCLE e aceito participar voluntariamente.'],
      similar_cases: 'Sim', shared_setting: ['Refeição ou alimento'], cluster_timing: 'Na mesma época',
      environment: ['Nenhuma destas situações'], animal: ['Nenhum evento animal relevante'],
      food: ['Leite cru ou queijo sem inspeção', 'Outras pessoas que consumiram também adoeceram'],
      exposure_specific: 'Queijo fresco', exposure_source: 'Banca da Feira Central',
      exposure_period: 'Manhã de 21/08/2026', exposed_count: '7', sick_count: '4',
      source_active_t0: 'Sim', others_still_exposed_t0: 'Sim', extra_symptoms: ['Diarreia'],
      understood_diagnosis: 'Virose ou síndrome viral indefinida', diagnosis_status: 'Suspeita',
      safety: [noCurrentDanger], days_unable: '3', expense_any: 'Sim', expense_total: '75',
      caregiver_stop: 'Não', open_exposure: ''
    },
    t10: {
      trajectory: 'Recuperado', safety: [noCurrentDanger], returned_care: 'Não',
      diagnosis_update: 'Não recebi informação', new_similar: 'Sim',
      new_similar_detail: 'Mais 3 pessoas, todas após a feira do fim de semana',
      new_common_exposure: 'Queijo fresco da mesma banca', new_exposure_info: 'Sim',
      new_exposure_detail: 'A banca ainda estava vendendo o mesmo produto', source_active: 'Sim',
      others_exposed: 'Sim', additional_days: '1', additional_expense_any: 'Não', lost_income_any: 'Não'
    },
    t30: {
      episode_ended: 'Sim', safety: [noCurrentDanger], activity_return: 'Retorno completo',
      activity_return_date: '2026-08-28', diagnosis_update: 'Sem mudança', new_similar: 'Não',
      source_new_info: 'Sim', source_new_detail: 'A Vigilância entrou em contato com o estabelecimento',
      source_active: 'Não', guidance_action: 'Sim', cases_after_action: 'Não',
      additional_days: '0', additional_expense_any: 'Não', lost_income_any: 'Não'
    }
  };

  const state = {
    stage: 't0',
    answers: { t0: {}, t10: {}, t30: {} },
    stageStartedAt: { t0: Date.now() },
    cohort: null,
    signals: [],
    currentScenarioKey: 'detectable',
    reviewOverrides: {}
  };

  function hasPositiveSelection(value, negativeLabel) {
    return Array.isArray(value) && value.length > 0 && !value.includes(negativeLabel);
  }

  function hasT0CollectiveDoor(answers) {
    return answers.similar_cases === 'Sim'
      || hasPositiveSelection(answers.environment, 'Nenhuma destas situações')
      || hasPositiveSelection(answers.animal, 'Nenhum evento animal relevante')
      || hasPositiveSelection(answers.food, 'Nenhuma destas exposições');
  }

  function priorT0ExposureMentioned() {
    const t0 = state.answers.t0 || {};
    return t0.similar_cases === 'Sim'
      || hasPositiveSelection(t0.environment, 'Nenhuma destas situações')
      || hasPositiveSelection(t0.animal, 'Nenhum evento animal relevante')
      || hasPositiveSelection(t0.food, 'Nenhuma destas exposições')
      || Boolean(String(t0.open_exposure || '').trim());
  }

  function priorCollectiveSignalMentioned() {
    const t10 = state.answers.t10 || {};
    return priorT0ExposureMentioned()
      || t10.new_similar === 'Sim'
      || t10.new_exposure_info === 'Sim';
  }

  function isVisible(item, answers) {
    return !item.showWhen || Boolean(item.showWhen(answers));
  }

  function isAnswered(item, value) {
    if (!item.required) return true;
    if (item.type === 'checkboxes') return Array.isArray(value) && value.length > 0;
    if (value === undefined || value === null || String(value).trim() === '') return false;
    if (item.type === 'number') {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return false;
      if (item.min !== undefined && numeric < Number(item.min)) return false;
      if (item.max !== undefined && numeric > Number(item.max)) return false;
    }
    return true;
  }

  function renderInput(item, stageKey) {
    const value = state.answers[stageKey][item.id];
    const name = `sfa_lab_${stageKey}_${item.id}`;
    const baseId = `sfa-lab-${stageKey}-${item.id}`;

    if (item.type === 'radio' || item.type === 'checkboxes') {
      const inputType = item.type === 'radio' ? 'radio' : 'checkbox';
      return `<div class="sfa-lab__options">${item.options.map((option, index) => {
        const optionId = `${baseId}-${index}`;
        const checked = item.type === 'radio'
          ? value === option
          : (Array.isArray(value) && value.includes(option));
        return `<div class="form-check">
          <input class="form-check-input" type="${inputType}" id="${escapeHtml(optionId)}"
                 name="${escapeHtml(name)}" value="${escapeHtml(option)}" ${checked ? 'checked' : ''}>
          <label class="form-check-label" for="${escapeHtml(optionId)}">${escapeHtml(option)}</label>
        </div>`;
      }).join('')}</div>`;
    }

    if (item.type === 'textarea') {
      return `<textarea class="form-control form-control-sm" id="${escapeHtml(baseId)}" name="${escapeHtml(name)}"
        rows="2" aria-required="${item.required ? 'true' : 'false'}" ${item.placeholder ? `placeholder="${escapeHtml(item.placeholder)}"` : ''}>${escapeHtml(value || '')}</textarea>`;
    }

    const inputType = ['number', 'date'].includes(item.type) ? item.type : 'text';
    return `<input class="form-control form-control-sm" type="${inputType}" id="${escapeHtml(baseId)}"
      name="${escapeHtml(name)}" value="${escapeHtml(value || '')}"
      aria-required="${item.required ? 'true' : 'false'}"
      ${item.placeholder ? `placeholder="${escapeHtml(item.placeholder)}"` : ''}
      ${item.min !== undefined ? `min="${escapeHtml(item.min)}"` : ''}
      ${item.max !== undefined ? `max="${escapeHtml(item.max)}"` : ''}
      ${item.step !== undefined ? `step="${escapeHtml(item.step)}"` : ''}>`;
  }

  function renderStage() {
    const stage = stages[state.stage];
    const answers = state.answers[state.stage];
    const host = byId('sfa-lab-form-host');
    byId('sfa-lab-validation').hidden = true;
    let questionIndex = 0;

    host.innerHTML = stage.sections.map((section, sectionIndex) => {
      const questionsHtml = section.questions.map((item) => {
        if (!item.conditional) questionIndex += 1;
        const visible = isVisible(item, answers);
        const displayedLabel = item.labelFor ? item.labelFor() : item.label;
        const classes = ['sfa-lab__question'];
        if (item.conditional) classes.push('is-conditional');
        if (item.safety) classes.push('sfa-lab__safety');
        return `<fieldset class="${classes.join(' ')}" data-question-id="${escapeHtml(item.id)}" aria-required="${item.required ? 'true' : 'false'}"
                  data-stage="${escapeHtml(state.stage)}" ${visible ? '' : 'hidden'}>
          <legend>
            <span class="sfa-lab__question-number">${item.conditional ? '↳' : `${questionIndex}.`}</span>
            ${escapeHtml(displayedLabel)}${item.required ? ' *' : ''}
            ${item.help ? `<span class="sfa-lab__question-help">${escapeHtml(item.help)}</span>` : ''}
          </legend>
          ${renderInput(item, state.stage)}
          ${item.safety ? '<div class="sfa-lab__safety-alert" data-safety-alert role="alert" aria-live="assertive" hidden><strong>Atenção:</strong> esta resposta não gera diagnóstico. Procure avaliação presencial imediatamente; em emergência, ligue 192.</div>' : ''}
        </fieldset>`;
      }).join('');
      return `<section class="sfa-lab__section" data-form-section="${sectionIndex}">
        <div class="sfa-lab__section-title"><span><i class="fas ${escapeHtml(section.icon)}" aria-hidden="true"></i></span>${escapeHtml(section.title)}</div>
        ${questionsHtml}
      </section>`;
    }).join('');

    bindStageInputs();
    applyVisibility();
    updateStageHeader();
    updateProgress();
    updateStageSummary();
  }

  function allQuestions(stageKey) {
    return stages[stageKey].sections.flatMap((section) => section.questions);
  }

  function questionById(stageKey, id) {
    return allQuestions(stageKey).find((item) => item.id === id);
  }

  function bindStageInputs() {
    byId('sfa-lab-form').querySelectorAll('input, textarea').forEach((input) => {
      const handler = () => {
        const wrapper = input.closest('[data-question-id]');
        if (!wrapper) return;
        const item = questionById(state.stage, wrapper.dataset.questionId);
        if (!item) return;

        if (item.type === 'checkboxes') {
          if (input.checked && item.exclusive && item.exclusive.includes(input.value)) {
            wrapper.querySelectorAll('input[type="checkbox"]').forEach((other) => {
              if (other !== input) other.checked = false;
            });
          } else if (input.checked && item.exclusive) {
            wrapper.querySelectorAll('input[type="checkbox"]').forEach((other) => {
              if (item.exclusive.includes(other.value)) other.checked = false;
            });
          }
          state.answers[state.stage][item.id] = Array.from(wrapper.querySelectorAll('input[type="checkbox"]:checked')).map((box) => box.value);
        } else if (item.type === 'radio') {
          state.answers[state.stage][item.id] = input.value;
        } else {
          state.answers[state.stage][item.id] = input.value;
        }

        applyVisibility();
        clearQuestionError(item);
        updateProgress();
        updateStageSummary();
      };
      input.addEventListener(input.type === 'text' || input.tagName === 'TEXTAREA' ? 'input' : 'change', handler);
    });
  }

  function clearQuestionError(item) {
    const wrapper = byId('sfa-lab-form').querySelector(`[data-question-id="${item.id}"]`);
    if (!wrapper || !isAnswered(item, state.answers[state.stage][item.id])) return;
    wrapper.classList.remove('has-error');
    wrapper.removeAttribute('aria-invalid');
    if (!visibleQuestions(state.stage).filter((entry) => entry.required).some((entry) => !isAnswered(entry, state.answers[state.stage][entry.id]))) {
      byId('sfa-lab-validation').hidden = true;
    }
  }

  function validateCurrentStage() {
    const missing = visibleQuestions(state.stage)
      .filter((item) => item.required && !isAnswered(item, state.answers[state.stage][item.id]));
    byId('sfa-lab-form').querySelectorAll('[data-question-id]').forEach((wrapper) => {
      wrapper.classList.remove('has-error');
      wrapper.removeAttribute('aria-invalid');
    });
    if (!missing.length) {
      byId('sfa-lab-validation').hidden = true;
      return true;
    }

    missing.forEach((item) => {
      const wrapper = byId('sfa-lab-form').querySelector(`[data-question-id="${item.id}"]`);
      if (!wrapper) return;
      wrapper.classList.add('has-error');
      wrapper.setAttribute('aria-invalid', 'true');
    });
    const feedback = byId('sfa-lab-validation');
    feedback.textContent = `Para simular o envio de ${stages[state.stage].label}, responda ${missing.length} campo(s) obrigatório(s) destacado(s).`;
    feedback.hidden = false;
    const first = byId('sfa-lab-form').querySelector(`[data-question-id="${missing[0].id}"]`);
    if (first) {
      first.scrollIntoView({ behavior: 'smooth', block: 'center' });
      const control = first.querySelector('input, textarea');
      if (control) control.focus({ preventScroll: true });
    }
    return false;
  }

  function applyVisibility() {
    const answers = state.answers[state.stage];
    allQuestions(state.stage).forEach((item) => {
      const wrapper = byId('sfa-lab-form').querySelector(`[data-question-id="${item.id}"]`);
      if (!wrapper) return;
      const visible = isVisible(item, answers);
      wrapper.hidden = !visible;
      if (!visible) return;

      if (item.safety) {
        const selected = Array.isArray(answers[item.id]) ? answers[item.id] : [];
        const hasDanger = selected.some((option) => option !== noCurrentDanger);
        const alert = wrapper.querySelector('[data-safety-alert]');
        if (alert) alert.hidden = !hasDanger;
      }
    });

    byId('sfa-lab-form').querySelectorAll('[data-form-section]').forEach((section) => {
      section.hidden = section.querySelectorAll('[data-question-id]:not([hidden])').length === 0;
    });
  }

  function updateStageHeader() {
    const name = (byId('sfa-lab-name').value || 'participante').trim();
    byId('sfa-lab-greeting').textContent = `Olá, ${name}.`;
    byId('sfa-lab-stage-purpose').textContent = stages[state.stage].purpose;

    root.querySelectorAll('[data-stage]').forEach((button) => {
      if (button.tagName !== 'BUTTON') return;
      const active = button.dataset.stage === state.stage;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });

    const nextButton = byId('sfa-lab-next');
    if (state.stage === 't0') {
      nextButton.innerHTML = 'Ir para T10 <i class="fas fa-arrow-right ms-1" aria-hidden="true"></i>';
      nextButton.hidden = false;
    } else if (state.stage === 't10') {
      nextButton.innerHTML = 'Ir para T30 <i class="fas fa-arrow-right ms-1" aria-hidden="true"></i>';
      nextButton.hidden = false;
    } else {
      nextButton.innerHTML = `Ver a coorte de ${COHORT_SIZE} <i class="fas fa-chart-column ms-1" aria-hidden="true"></i>`;
      nextButton.hidden = false;
    }
  }

  function visibleQuestions(stageKey) {
    const answers = state.answers[stageKey];
    return allQuestions(stageKey).filter((item) => isVisible(item, answers));
  }

  function updateProgress() {
    const visible = visibleQuestions(state.stage).filter((item) => item.required);
    const answered = visible.filter((item) => isAnswered(item, state.answers[state.stage][item.id])).length;
    const value = percent(answered, visible.length);
    const progress = byId('sfa-lab-progress');
    progress.style.width = `${value}%`;
    const bar = progress.parentElement;
    bar.setAttribute('aria-valuenow', String(value));
    bar.setAttribute('aria-label', `${answered} de ${visible.length} perguntas obrigatórias respondidas`);
  }

  function updateStageSummary() {
    const visible = visibleQuestions(state.stage);
    const required = visible.filter((item) => item.required);
    const conditional = visible.filter((item) => item.conditional).length;
    const seconds = visible.reduce((total, item) => total + (item.seconds || 12), 0);
    const lowMinutes = Math.max(1, Math.floor(seconds / 60));
    const highMinutes = Math.max(lowMinutes + 1, Math.ceil(seconds / 60) + 1);
    byId('sfa-lab-time').dataset.estimate = `estimado ${lowMinutes}–${highMinutes} min`;
    updateTimeBadge();

    const stage = stages[state.stage];
    byId('sfa-lab-stage-summary').innerHTML = `
      <div class="sfa-lab__summary-metric"><span>Perguntas visíveis</span><strong>${visible.length}</strong></div>
      <div class="sfa-lab__summary-metric"><span>Obrigatórias neste percurso</span><strong>${required.length}</strong></div>
      <div class="sfa-lab__summary-metric"><span>Detalhes abertos por respostas</span><strong>${conditional}</strong></div>
      <ul class="sfa-lab__summary-list">${stage.summary.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
    byId('sfa-lab-imported-fields').innerHTML = stage.imported.map((item) => `<span>${escapeHtml(item)}</span>`).join('');
  }

  function switchStage(stageKey) {
    if (!stages[stageKey]) return;
    state.stage = stageKey;
    state.stageStartedAt[stageKey] = Date.now();
    renderStage();
    byId('sfa-lab-announcer').textContent = `Etapa ${stages[stageKey].label} aberta.`;
  }

  function updateTimeBadge() {
    const badge = byId('sfa-lab-time');
    if (!badge) return;
    const startedAt = state.stageStartedAt[state.stage] || Date.now();
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, '0');
    const seconds = String(elapsedSeconds % 60).padStart(2, '0');
    badge.textContent = `${badge.dataset.estimate || 'estimativa pendente'} · teste ${minutes}:${seconds}`;
  }

  function switchView(view) {
    root.querySelectorAll('[data-lab-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.labPanel !== view;
    });
    root.querySelectorAll('[data-lab-view]').forEach((button) => {
      const active = button.dataset.labView === view;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    });
    if (view === 'cohort') renderCohort();
    byId('sfa-lab-announcer').textContent = `Módulo ${view === 'participant' ? 'experiência do participante' : view === 'cohort' ? 'coorte sintética' : 'julgamento de utilidade'} aberto.`;
  }

  function simulatedDecision(id, label, day, status, owner, contribution, evidence, requiredFields, peopleReached) {
    return {
      id,
      label,
      day,
      status,
      owner,
      reportContribution: contribution,
      evidence,
      requiredFields,
      peopleReached,
      attributedToReport: contribution !== 'Não relacionada'
    };
  }

  const scenarioDefinitions = {
    detectable: {
      description: 'Cinco pistas sentinela coexistem entre 100 respostas: coadoecimento alimentar, lama com sinais de roedores, carrapatos, concentração territorial de mosquitos e um evento coletivo. São hipóteses para verificação humana, não diagnósticos.',
      t10Count: 86,
      t30Count: 76,
      ial: { eligible: 72, collected: 62, valid: 58, positive: 24 },
      clusters: [
        {
          key: 'food:almoco-comunitario', label: 'Alimento compartilhado — almoço comunitário', domain: 'Alimento/água/produto',
          size: 8, onsetStart: 3, onsetSpan: 3, location: 'Centro comunitário', potentialExposed: 34,
          sinanVisible: false, active: true, sourceStateT30: 'Aparentemente interrompida',
          action: true, postActionCases: false, discoverAt: 'T0', windowDays: 7, reviewStatus: 'accepted',
          matchReason: 'Mesmo alimento e evento, com oito participantes e inícios concentrados em três dias.', confidence: 0.97,
          decisions: [
            simulatedDecision('D-SIM-001', 'Verificação do preparo e dos alimentos servidos', 8, 'Executada', 'Vigilância Sanitária', 'Principal', ['T0: item/origem', 'T0: coadoecidos'], ['exposure', 'place', 'date'], 8),
            simulatedDecision('D-SIM-002', 'Orientação aos participantes do evento', 9, 'Executada', 'Vigilância Epidemiológica', 'Principal', ['T0: coadoecidos', 'T10: pessoas expostas'], ['exposure', 'place', 'followup', 'active'], 26),
            simulatedDecision('D-SIM-003', 'Rastreio de ingredientes e fornecedores', 10, 'Em andamento', 'Vigilância Sanitária', 'Contributiva', ['T0: item/origem/local'], ['exposure', 'place', 'date'], 3)
          ]
        },
        {
          key: 'environment:lama-roedores-jardim', label: 'Lama e sinais de roedores — após alagamento', domain: 'Ambiente/água',
          size: 6, onsetStart: 9, onsetSpan: 5, location: 'Jardim das Flores', potentialExposed: 19,
          sinanVisible: false, active: true, sourceStateT30: 'Ainda ativa',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 14, reviewStatus: 'accepted',
          matchReason: 'Mesmo trecho alagado, contato com lama e sinais de roedores em janela compatível com uma exposição de risco; a hipótese de leptospirose depende de avaliação epidemiológica e clínica.', confidence: 0.93,
          decisions: [
            simulatedDecision('D-SIM-004', 'Inspeção ambiental do trecho alagado', 15, 'Em andamento', 'Vigilância Ambiental', 'Principal', ['T0: lama/enchente', 'T0: local e período'], ['exposure', 'place', 'date', 'active'], 6),
            simulatedDecision('D-SIM-005', 'Orientação sobre contato com lama e roedores', 16, 'Registrada', 'Vigilância Epidemiológica', 'Contributiva', ['T0: pessoas ainda expostas'], ['exposure', 'place', 'active'], 19)
          ]
        },
        {
          key: 'animal:fazenda-santa-clara', label: 'Carrapatos — Fazenda Santa Clara', domain: 'Animal/rural',
          size: 5, onsetStart: 18, onsetSpan: 4, location: 'Fazenda Santa Clara', potentialExposed: 11,
          sinanVisible: false, active: true, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 14, reviewStatus: 'accepted',
          matchReason: 'Mesma propriedade, mesmo evento com carrapatos e janela compatível.', confidence: 0.91,
          decisions: [
            simulatedDecision('D-SIM-006', 'Articulação para verificação One Health', 23, 'Registrada', 'Vigilância Epidemiológica', 'Contributiva', ['T0: evento animal e propriedade'], ['exposure', 'place'], 5)
          ]
        },
        {
          key: 'vector:mosquitos-jardim-boa-vista', label: 'Muitos mosquitos — Jardim Boa Vista', domain: 'Vetor/território',
          size: 7, onsetStart: 25, onsetSpan: 6, location: 'Jardim Boa Vista', potentialExposed: 42,
          sinanVisible: true, active: true, sourceStateT30: 'Esclarecida, mas não interrompida',
          action: true, postActionCases: true, discoverAt: 'T10', windowDays: 14, reviewStatus: 'accepted',
          matchReason: 'Relatos repetidos de alta presença de mosquitos no mesmo território; o sinal orienta verificação vetorial e não atribui a febre aos mosquitos.', confidence: 0.88,
          decisions: [
            simulatedDecision('D-SIM-007', 'Vistoria de possíveis criadouros no território', 31, 'Executada', 'Controle de Vetores', 'Principal', ['T0: vetores/território', 'T10: fonte ativa'], ['exposure', 'place', 'followup', 'active'], 42),
            simulatedDecision('D-SIM-008', 'Reforço de orientação para eliminação de criadouros', 32, 'Executada', 'Controle de Vetores', 'Contributiva', ['T10: pessoas ainda expostas'], ['exposure', 'place', 'followup'], 42)
          ]
        },
        {
          key: 'event:escola-aurora', label: 'Evento — Escola Municipal Aurora', domain: 'Trabalho/escola/evento',
          size: 4, onsetStart: 36, onsetSpan: 3, location: 'Escola Municipal Aurora', potentialExposed: 18,
          sinanVisible: true, active: false, sourceStateT30: 'Aparentemente interrompida',
          action: true, postActionCases: false, discoverAt: 'T10', windowDays: 7, reviewStatus: 'accepted',
          matchReason: 'Mesma instituição e mesmo evento informados no T10.', confidence: 0.94,
          decisions: [
            simulatedDecision('D-SIM-009', 'Contato com a instituição', 40, 'Executada', 'Vigilância Epidemiológica', 'Contributiva', ['SINAN: tempo/território', 'T10: evento específico'], ['exposure', 'place', 'followup'], 4),
            simulatedDecision('D-SIM-010', 'Orientação ao grupo exposto', 41, 'Executada', 'Vigilância Epidemiológica', 'Contributiva', ['T10: instituição e coexpostos'], ['exposure', 'place', 'followup'], 18)
          ]
        }
      ]
    },
    sporadic: {
      description: 'Exposições variadas e pouco específicas, sem duas pessoas diretamente ligadas à mesma fonte. O resultado honesto é não abrir uma fila artificial de sinais.',
      t10Count: 84,
      t30Count: 74,
      ial: { eligible: 68, collected: 56, valid: 52, positive: 16 },
      clusters: []
    },
    attrition: {
      description: 'Dois vínculos surgem no T0, mas apenas 58 pessoas respondem ao T10 e 40 ao T30. A detecção permanece; urgência e encerramento ficam incompletos.',
      t10Count: 58,
      t30Count: 40,
      ial: { eligible: 70, collected: 50, valid: 44, positive: 14 },
      clusters: [
        {
          key: 'water:corrego-bebedouro', label: 'Água — córrego próximo ao bebedouro', domain: 'Ambiente/água',
          size: 6, onsetStart: 6, onsetSpan: 4, location: 'Zona rural norte', potentialExposed: 15,
          sinanVisible: false, active: true, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 14,
          matchReason: 'Mesmo córrego e período de exposição; seguimento incompleto.', confidence: 0.84,
          decisions: []
        },
        {
          key: 'food:lanche-evento', label: 'Lanche — evento comunitário', domain: 'Alimento/água/produto',
          size: 4, onsetStart: 18, onsetSpan: 3, location: 'Centro comunitário', potentialExposed: 30,
          sinanVisible: true, active: null, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 7,
          matchReason: 'Mesmo evento e inícios em três dias; fonte ainda pouco específica.', confidence: 0.76,
          decisions: []
        }
      ]
    },
    semantic: {
      description: 'Seis participantes descrevem a mesma exposição com grafias diferentes. A normalização apenas sugere a correspondência; a validação continua humana.',
      t10Count: 90,
      t30Count: 82,
      ial: { eligible: 74, collected: 66, valid: 62, positive: 26 },
      clusters: [
        {
          key: 'food:queijo-minas-banca-primavera', normalizedKey: 'food:queijo-minas-banca-primavera',
          label: 'Queijo Minas — Banca Primavera', normalizedLabel: 'Queijo Minas da Banca Primavera',
          domain: 'Alimento/água/produto', size: 6, onsetStart: 5, onsetSpan: 4,
          location: 'Banca Primavera — Feira Central', potentialExposed: 21,
          sinanVisible: false, active: true, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 7,
          matchReason: '“queijo minas”, “queijo fresco” e “queijo da banca Primavera”; local e período coincidem.',
          confidence: 0.92,
          variants: [
            { key: 'raw:queijo-minas-primavera', label: 'queijo minas da Primavera' },
            { key: 'raw:queijo-fresco-feira', label: 'queijo fresco da feira' },
            { key: 'raw:queijo-banca-primavera', label: 'queijo comprado na banca Primavera' }
          ],
          decisions: [
            simulatedDecision('D-SIM-SEM-001', 'Verificação da banca e origem do produto', 11, 'Registrada', 'Vigilância Sanitária', 'Principal', ['T0: descrições normalizadas', 'T0: fonte e período'], ['exposure', 'place', 'date'], 6)
          ]
        }
      ]
    },
    falsefriends: {
      description: 'Expressões parecidas escondem duas fontes e dois locais distintos. O sistema deve mostrar a dúvida para rejeição humana, não fundir casos automaticamente.',
      t10Count: 88,
      t30Count: 78,
      ial: { eligible: 66, collected: 58, valid: 54, positive: 18 },
      clusters: [
        {
          key: 'candidate:lanche-primavera', normalizedKey: 'candidate:lanche-primavera',
          label: '“Lanche Primavera”', normalizedLabel: 'Lanche Primavera (fonte ainda ambígua)',
          domain: 'Alimento/água/produto', size: 4, onsetStart: 9, onsetSpan: 3,
          location: 'Fontes distintas', potentialExposed: 27,
          sinanVisible: false, active: null, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 7,
          matchReason: 'O nome é parecido, mas os relatos apontam estabelecimentos e bairros diferentes.',
          confidence: 0.46,
          variants: [
            { key: 'raw:lanche-primavera-norte', label: 'lanche Primavera', location: 'Centro Comunitário Norte' },
            { key: 'raw:combo-primavera-sul', label: 'combo primavera', location: 'Escola Municipal Sul' }
          ],
          decisions: []
        }
      ]
    },
    onehealth: {
      description: 'Um evento de adoecimento animal e exposição humana na mesma propriedade permanece ativo. A fila explicita a articulação One Health sem inferir etiologia.',
      t10Count: 92,
      t30Count: 84,
      ial: { eligible: 78, collected: 70, valid: 64, positive: 20 },
      clusters: [
        {
          key: 'animal:abortos-sitio-boa-esperanca', label: 'Abortos em caprinos — Sítio Boa Esperança',
          normalizedLabel: 'Evento reprodutivo animal — Sítio Boa Esperança', domain: 'Animal/rural',
          size: 5, onsetStart: 12, onsetSpan: 5, location: 'Sítio Boa Esperança', potentialExposed: 12,
          sinanVisible: false, active: true, sourceStateT30: 'Ainda ativa',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 14,
          matchReason: 'Mesma propriedade, contato com parto/placenta e evento animal incomum no mesmo período.',
          confidence: 0.9,
          decisions: [
            simulatedDecision('D-SIM-OH-001', 'Verificação conjunta na propriedade', 18, 'Em andamento', 'Vigilância Epidemiológica e serviço veterinário', 'Principal', ['T0: espécie/evento', 'T0: fonte ativa e coexpostos'], ['exposure', 'place', 'date', 'active'], 5),
            simulatedDecision('D-SIM-OH-002', 'Orientação preventiva aos expostos', 19, 'Registrada', 'Vigilância Epidemiológica', 'Contributiva', ['T0: pessoas ainda expostas'], ['exposure', 'place', 'active'], 12)
          ]
        }
      ]
    }
  };

  function responseSelected(index, count, salt) {
    return ((index * 17 + salt) % COHORT_SIZE) < count;
  }

  function deterministicSubset(indexes, count, salt) {
    return indexes.slice()
      .sort((a, b) => ((((a + 1) * 31) + salt) % 101) - ((((b + 1) * 31) + salt) % 101))
      .slice(0, Math.min(count, indexes.length));
  }

  function buildSyntheticCohort(scenarioKey) {
    const scenario = scenarioDefinitions[scenarioKey];
    const assignments = new Map();
    let cursor = 0;
    scenario.clusters.forEach((cluster) => {
      for (let within = 0; within < cluster.size && cursor < COHORT_SIZE; within += 1) {
        assignments.set(cursor, { cluster, within });
        cursor += 1;
      }
    });

    const neighborhoods = ['Centro', 'Jardim Boa Vista', 'Vila Bucci', 'Jardim Teixeira', 'Zona rural'];
    const diagnoses = ['Dengue', 'Sem definição', 'Dengue', 'Chikungunya', 'Sem definição'];
    const broadDomains = ['Ambiente/água', 'Animal/rural', 'Alimento/água/produto', 'Trabalho/escola/evento'];
    const participantIndexes = Array.from({ length: COHORT_SIZE }, (_, index) => index);
    const t10Indexes = participantIndexes.filter((index) => responseSelected(index, scenario.t10Count, 7));
    const t10Set = new Set(t10Indexes);
    const t30Set = new Set(t10Indexes
      .slice()
      .sort((a, b) => (((a * 23) + 13) % 101) - (((b * 23) + 13) % 101))
      .slice(0, scenario.t30Count));
    const ialPlan = Object.assign({ eligible: 35, collected: 30, valid: 28, positive: 9 }, scenario.ial || {});
    const ialEligibleIndexes = deterministicSubset(participantIndexes, ialPlan.eligible, 5);
    const ialCollectedIndexes = deterministicSubset(ialEligibleIndexes, ialPlan.collected, 17);
    const ialValidIndexes = deterministicSubset(ialCollectedIndexes, ialPlan.valid, 29);
    const ialPositiveIndexes = deterministicSubset(ialValidIndexes, ialPlan.positive, 41);
    const ialEligibleSet = new Set(ialEligibleIndexes);
    const ialCollectedSet = new Set(ialCollectedIndexes);
    const ialValidSet = new Set(ialValidIndexes);
    const ialPositiveSet = new Set(ialPositiveIndexes);

    return Array.from({ length: COHORT_SIZE }, (_, index) => {
      const assigned = assignments.get(index);
      const cluster = assigned ? assigned.cluster : null;
      const variant = cluster && Array.isArray(cluster.variants) && cluster.variants.length
        ? cluster.variants[assigned.within % cluster.variants.length]
        : null;
      const t10Responded = t10Set.has(index);
      const t30Responded = t30Set.has(index);
      const recordedDiagnosis = diagnoses[index % diagnoses.length];
      const understoodDiagnosis = index % 6 === 0
        ? (recordedDiagnosis === 'Dengue' ? 'Virose/indefinida' : 'Dengue')
        : recordedDiagnosis;
      const hasBroadExposure = !cluster && index % 8 === 0;
      const exposurePlace = cluster ? ((variant && variant.location) || cluster.location) : null;
      const exposureDateKnown = Boolean(cluster && cluster.dateKnown !== false);
      const linkComplete = Boolean(cluster && exposurePlace && exposureDateKnown
        && (cluster.completeLinks === undefined || assigned.within < cluster.completeLinks));
      const ialValidResult = ialValidSet.has(index);
      const ialEtiologyPositive = ialPositiveSet.has(index);

      return {
        id: `P${String(index + 1).padStart(3, '0')}`,
        onsetDay: cluster ? cluster.onsetStart + (assigned.within % cluster.onsetSpan) : 1 + ((index * 7) % 30),
        neighborhood: cluster ? exposurePlace : neighborhoods[index % neighborhoods.length],
        exposureKey: cluster ? ((variant && variant.key) || cluster.key) : (hasBroadExposure ? `broad:${index}` : null),
        normalizedExposureKey: cluster ? (cluster.normalizedKey || cluster.key) : null,
        exposureLabel: cluster ? ((variant && variant.label) || cluster.label) : (hasBroadExposure ? 'Exposição inespecífica isolada' : null),
        normalizedExposureLabel: cluster ? (cluster.normalizedLabel || cluster.label) : null,
        exposureDomain: cluster ? cluster.domain : (hasBroadExposure ? broadDomains[index % broadDomains.length] : null),
        specificity: cluster ? 'specific' : (hasBroadExposure ? 'broad' : 'none'),
        exposurePlace,
        exposureDateKnown,
        linkComplete,
        hasNewInformation: Boolean(cluster || hasBroadExposure),
        reportedOthers: cluster ? 1 + (index % 3) : (index % 11 === 0 ? 1 : 0),
        t10Responded,
        t30Responded,
        sourceActiveT10: cluster && t10Responded ? cluster.active : null,
        sourceStateT30: cluster && t30Responded ? cluster.sourceStateT30 : null,
        actionObservedT30: Boolean(cluster && t30Responded && cluster.action),
        postActionCases: cluster && t30Responded ? cluster.postActionCases : null,
        decisions: cluster ? (cluster.decisions || []) : [],
        discoverAt: cluster ? cluster.discoverAt : null,
        windowDays: cluster ? (cluster.windowDays || 7) : 7,
        defaultReviewStatus: cluster ? (cluster.reviewStatus || 'pending') : 'pending',
        matchReason: cluster ? cluster.matchReason : null,
        matchConfidence: cluster && Number.isFinite(cluster.confidence) ? cluster.confidence : 0.5,
        sinanVisible: Boolean(cluster && cluster.sinanVisible),
        potentialExposed: cluster ? cluster.potentialExposed : 0,
        ialEligible: ialEligibleSet.has(index),
        ialSampleCollected: ialCollectedSet.has(index),
        ialValidResult,
        ialEtiologyPositive,
        ialEtiology: ialEtiologyPositive ? (index % 4 === 0 ? 'Chikungunya' : 'Dengue') : null,
        ialStratum: ialValidResult ? (ialEtiologyPositive ? 'Etiologia detectada' : 'Sem etiologia detectada') : 'Sem resultado válido',
        recordedDiagnosis,
        understoodDiagnosis,
        daysUnable: 1 + ((index * 3) % 7),
        expense: index % 4 === 0 ? 0 : 25 + ((index * 19) % 180)
      };
    });
  }

  function buildSignals(records, reviewOverrides) {
    const overrides = reviewOverrides || {};
    const grouped = new Map();
    records.forEach((record) => {
      if (!record.exposureKey || record.specificity !== 'specific') return;
      const groupingKey = record.normalizedExposureKey || record.exposureKey;
      if (!grouped.has(groupingKey)) grouped.set(groupingKey, []);
      grouped.get(groupingKey).push(record);
    });

    return Array.from(grouped.entries()).map(([groupingKey, group]) => {
      const configuredStage = group[0].discoverAt || 'T0';
      const available = group.filter((record) => configuredStage === 'T0'
        || (configuredStage === 'T10' && record.t10Responded)
        || (configuredStage === 'T30' && record.t30Responded));
      if (!available.length) return null;

      const ordered = available.slice().sort((a, b) => a.onsetDay - b.onsetDay);
      const windowDays = available[0].windowDays || 7;
      const withinWindow = ordered[ordered.length - 1].onsetDay - ordered[0].onsetDay <= windowDays;
      const reportedOthers = Math.max(...available.map((record) => record.reportedOthers || 0));
      if ((available.length < 2 && reportedOthers < 1) || !withinWindow) return null;

      const first = available[0];
      const activeValues = group
        .filter((record) => record.t10Responded && typeof record.sourceActiveT10 === 'boolean')
        .map((record) => record.sourceActiveT10);
      const activeState = activeValues.includes(true) && activeValues.includes(false)
        ? 'Conflitante'
        : (activeValues.includes(true) ? true : (activeValues.includes(false) ? false : null));
      const t30States = group
        .filter((record) => record.t30Responded && record.sourceStateT30)
        .map((record) => record.sourceStateT30);
      const finalSourceState = t30States.includes('Ainda ativa')
        ? 'Ainda ativa'
        : (t30States.includes('Esclarecida, mas não interrompida')
          ? 'Esclarecida, mas não interrompida'
          : (t30States.includes('Aparentemente interrompida') ? 'Aparentemente interrompida' : 'Desconhecida'));
      const action = group.some((record) => record.actionObservedT30);
      const noPostActionCases = action && group.some((record) => record.postActionCases === false);
      const locations = new Set(available.map((record) => String(record.exposurePlace || '').trim().toLocaleLowerCase('pt-BR')).filter(Boolean));
      const sourceConsistent = locations.size <= 1;
      const linkCompleteCases = available.filter((record) => record.linkComplete !== false
        && record.exposurePlace && record.exposureDateKnown).length;
      const actionable = linkCompleteCases > 0 && sourceConsistent;
      const candidateStatus = overrides[groupingKey] || first.defaultReviewStatus || 'pending';
      const reviewStatus = ['pending', 'accepted', 'rejected'].includes(candidateStatus) ? candidateStatus : 'pending';
      let status = 'Revisar';
      let statusClass = 'is-review';
      if (finalSourceState === 'Aparentemente interrompida') {
        status = noPostActionCases
          ? 'Aparentemente interrompida; sem novos casos conhecidos'
          : 'Aparentemente interrompida';
        statusClass = 'is-closed';
      } else if (finalSourceState === 'Ainda ativa' || finalSourceState === 'Esclarecida, mas não interrompida' || activeState === true) {
        status = finalSourceState === 'Desconhecida' ? 'Fonte possivelmente ativa no T10' : finalSourceState;
        statusClass = 'is-urgent';
      } else if (activeState === 'Conflitante') {
        status = 'Informação conflitante sobre permanência';
      } else if (action) {
        status = noPostActionCases ? 'Ação percebida; sem novos casos conhecidos' : 'Ação percebida';
        statusClass = 'is-closed';
      }

      return {
        key: groupingKey,
        label: first.normalizedExposureLabel || first.exposureLabel,
        normalizedLabel: first.normalizedExposureLabel || first.exposureLabel,
        domain: first.exposureDomain,
        directCases: available.length,
        baseDirectCases: first.sinanVisible ? group.length : 0,
        reportedOthers,
        potentialExposed: first.potentialExposed,
        stage: configuredStage,
        stageCoverage: `${available.length}/${group.length}`,
        t10Coverage: `${group.filter((record) => record.t10Responded).length}/${group.length}`,
        t30Coverage: `${group.filter((record) => record.t30Responded).length}/${group.length}`,
        sinanVisible: first.sinanVisible,
        active: finalSourceState === 'Ainda ativa' || finalSourceState === 'Esclarecida, mas não interrompida' || activeState === true,
        activeState,
        finalSourceState,
        action,
        noPostActionCases,
        actionable,
        linkCompleteCases,
        sourceConsistent,
        reviewStatus,
        matchReason: first.matchReason || `Mesma descrição específica, local compatível e início dentro de ${windowDays} dias.`,
        confidence: clamp(Number(first.matchConfidence) || 0.5, 0, 1),
        evidenceStrength: available.length >= 2 ? 'A — vínculo direto' : 'B — coadoecido relatado',
        windowDays,
        earliestOnsetDay: ordered[0].onsetDay,
        decisions: first.decisions || [],
        status,
        statusClass,
        nextStep: nextStepForDomain(first.exposureDomain)
      };
    }).filter(Boolean);
  }

  function nextStepForDomain(domain) {
    const steps = {
      'Alimento/água/produto': 'Verificar item, origem, lote/local e coexpostos',
      'Animal/rural': 'Verificar evento animal, propriedade e pessoas expostas',
      'Ambiente/água': 'Verificar local, água/ambiente e permanência do risco',
      'Vetor/território': 'Verificar concentração territorial, criadouros e necessidade de ação vetorial',
      'Trabalho/escola/evento': 'Contatar instituição e avaliar busca/orientação'
    };
    return steps[domain] || 'Revisar vínculo, tempo e local';
  }

  function reviewOverridesFor(scenarioKey) {
    return state.reviewOverrides[scenarioKey] || {};
  }

  function setSignalReview(signalKey, reviewStatus, scenarioKey) {
    if (!['pending', 'accepted', 'rejected'].includes(reviewStatus)) {
      throw new Error(`Situação de revisão inválida: ${reviewStatus}`);
    }
    const selectedScenario = scenarioKey || state.currentScenarioKey || 'detectable';
    if (!state.reviewOverrides[selectedScenario]) state.reviewOverrides[selectedScenario] = {};
    state.reviewOverrides[selectedScenario][signalKey] = reviewStatus;
    return reviewStatus;
  }

  function acceptSignal(signalKey, scenarioKey) {
    return setSignalReview(signalKey, 'accepted', scenarioKey);
  }

  function rejectSignal(signalKey, scenarioKey) {
    return setSignalReview(signalKey, 'rejected', scenarioKey);
  }

  function buildFunnel(records, signals) {
    const acceptedSignals = signals.filter((signal) => signal.reviewStatus === 'accepted');
    const actionableSignals = acceptedSignals.filter((signal) => signal.actionable);
    return [
      { key: 'cohort', label: 'Participantes no T0', value: records.length, denominator: records.length, unit: 'pessoas' },
      { key: 'new-information', label: 'Informação nova além dos importados', value: records.filter((record) => record.hasNewInformation).length, denominator: records.length, unit: 'pessoas' },
      { key: 'complete-links', label: 'Participantes com vínculo minimamente completo', value: records.filter((record) => record.linkComplete).length, denominator: records.length, unit: 'pessoas' },
      { key: 'candidate-signals', label: 'Sinais únicos candidatos', value: signals.length, denominator: null, unit: 'sinais' },
      { key: 'validated-signals', label: 'Sinais aceitos na revisão humana', value: acceptedSignals.length, denominator: signals.length, unit: 'sinais' },
      { key: 'actionable-signals', label: 'Sinais aceitos e acionáveis', value: actionableSignals.length, denominator: acceptedSignals.length, unit: 'sinais' },
      { key: 'decisions', label: 'Decisões concretas registradas', value: registeredDecisions(signals).length, denominator: actionableSignals.length, unit: 'decisões', primary: true }
    ];
  }

  function buildIalSummary(records) {
    const eligible = records.filter((record) => record.ialEligible);
    const collected = eligible.filter((record) => record.ialSampleCollected);
    const valid = collected.filter((record) => record.ialValidResult);
    const positive = valid.filter((record) => record.ialEtiologyPositive);
    return [
      { key: 'eligible', label: 'Elegíveis no fluxo disponível', value: eligible.length, denominator: records.length },
      { key: 'collected', label: 'Amostras coletadas', value: collected.length, denominator: eligible.length },
      { key: 'valid', label: 'Resultados válidos', value: valid.length, denominator: collected.length },
      { key: 'yield', label: 'Etiologia detectada', value: positive.length, denominator: valid.length, stratifier: true }
    ];
  }

  function renderCohort() {
    const scenarioKey = byId('sfa-lab-scenario').value;
    const scenario = scenarioDefinitions[scenarioKey];
    state.currentScenarioKey = scenarioKey;
    state.cohort = buildSyntheticCohort(scenarioKey);
    state.signals = buildSignals(state.cohort, reviewOverridesFor(scenarioKey));
    byId('sfa-lab-scenario-description').textContent = scenario.description;

    renderFunnel(state.cohort, state.signals);
    renderKpis(state.cohort, state.signals);
    renderCounterfactual(state.cohort, state.signals);
    renderFollowup(state.cohort);
    renderDomains(state.cohort);
    renderSignals(state.signals);
    renderAiReview(state.signals);
    renderIal(state.cohort);
    renderDataPreview(state.cohort);
    renderDecisionRegistry(state.cohort, state.signals);
    renderAblation();
    renderQuestionUtility();
    syncPrecisionToCohort();
  }

  function registeredDecisions(signals) {
    return signals
      .filter((signal) => signal.reviewStatus === 'accepted' && signal.actionable)
      .flatMap((signal) => (signal.decisions || [])
      .filter((decision) => decision.attributedToReport)
      .map((decision) => Object.assign({ signalKey: signal.key, signalLabel: signal.label, earliestOnsetDay: signal.earliestOnsetDay }, decision)));
  }

  function renderFunnel(records, signals) {
    const host = byId('sfa-lab-funnel');
    if (!host) return;
    host.innerHTML = buildFunnel(records, signals).map((step) => {
      const denominator = step.denominator > 0 ? ` de ${step.denominator}` : '';
      return `<div class="sfa-lab__funnel-step ${step.primary ? 'is-primary' : ''}">
        <strong>${step.value}${denominator}</strong>
        <span>${escapeHtml(step.label)} · ${escapeHtml(step.unit)}</span>
      </div>`;
    }).join('');
  }

  function renderAiReview(signals) {
    const body = byId('sfa-lab-ai-review');
    if (!body) return;
    const empty = byId('sfa-lab-ai-review-empty');
    if (!signals.length) {
      body.innerHTML = '';
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    const reviewLabels = { pending: 'Pendente', accepted: 'Aceito', rejected: 'Rejeitado' };
    body.innerHTML = signals.map((signal) => `<tr>
      <td><strong>${escapeHtml(signal.normalizedLabel)}</strong>
        <div class="small text-muted">${signal.directCases} participante(s) diretamente observado(s)${signal.reportedOthers ? `; até ${signal.reportedOthers} coadoecido(s) apenas relatado(s)` : ''}</div>
      </td>
      <td class="small">${escapeHtml(signal.matchReason)}
        ${signal.sourceConsistent ? '' : '<div class="text-danger mt-1">Fontes/locais conflitantes: não acionável sem esclarecimento.</div>'}
      </td>
      <td><strong>${Math.round(signal.confidence * 100)}%</strong><div class="small text-muted">sem inferência diagnóstica</div></td>
      <td>
        <span class="sfa-lab__review-status is-${escapeHtml(signal.reviewStatus)}">${escapeHtml(reviewLabels[signal.reviewStatus])}</span>
        <div class="d-flex flex-wrap gap-1 mt-2">
          <button type="button" class="btn btn-outline-success btn-sm" data-sfa-review-action="accepted" data-signal-key="${escapeHtml(signal.key)}" aria-pressed="${signal.reviewStatus === 'accepted'}">Aceitar</button>
          <button type="button" class="btn btn-outline-danger btn-sm" data-sfa-review-action="rejected" data-signal-key="${escapeHtml(signal.key)}" aria-pressed="${signal.reviewStatus === 'rejected'}">Rejeitar</button>
        </div>
      </td>
    </tr>`).join('');
  }

  function renderIal(records) {
    const host = byId('sfa-lab-ial');
    if (!host) return;
    host.innerHTML = buildIalSummary(records).map((step) => {
      const rate = step.denominator > 0 ? percent(step.value, step.denominator) : 0;
      return `<div class="sfa-lab__ial-step">
        <strong>${step.value}/${step.denominator}</strong>
        <span>${escapeHtml(step.label)} (${rate}%)${step.stratifier ? ' · estratificador, não desfecho primário' : ''}</span>
      </div>`;
    }).join('');
  }

  const coreUtilityQuestions = new Set([
    'similar_cases', 'shared_setting', 'cluster_timing', 'environment', 'animal', 'animal_detail', 'food',
    'exposure_specific', 'exposure_source', 'exposure_period', 'exposed_count', 'sick_count',
    'source_active_t0', 'others_still_exposed_t0', 'new_similar', 'new_similar_detail',
    'new_common_exposure', 'new_exposure_info', 'new_exposure_detail', 'source_active', 'others_exposed',
    'source_new_info', 'source_new_detail', 'guidance_action', 'cases_after_action',
    'understood_diagnosis', 'diagnosis_status', 'diagnosis_update', 'diagnosis_now', 'diagnosis_final'
  ]);
  const ethicalUtilityQuestions = new Set(['respondent_role', 'respondent_name', 'consent']);

  function syntheticAnswer(stageKey, item) {
    const value = (exampleAnswers[stageKey] || {})[item.id];
    if (Array.isArray(value)) return value.join('; ');
    if (value !== undefined && value !== null && String(value).trim()) return String(value);
    return item.conditional ? 'Não exibida neste percurso' : 'Resposta sintética variável';
  }

  function utilityClassification(item) {
    if (ethicalUtilityQuestions.has(item.id)) {
      return { label: 'Ética / respondente', modifier: 'is-safety', impact: 'Perde consentimento ou identificação de quem forneceu a informação.' };
    }
    if (item.safety) {
      return { label: 'Segurança', modifier: 'is-safety', impact: 'Perde a orientação imediata diante de sinal de alarme.' };
    }
    if (coreUtilityQuestions.has(item.id)) {
      return { label: item.conditional ? 'Núcleo condicional' : 'Núcleo', modifier: 'is-core', impact: 'Reduz a capacidade de localizar, validar ou agir sobre a exposição coletiva.' };
    }
    if (item.conditional) {
      return { label: 'Condicional', modifier: 'is-conditional', impact: 'Perde detalhe apenas quando a pergunta-gatilho é positiva.' };
    }
    return { label: 'Manter', modifier: 'is-core', impact: 'Reduz contexto, seguimento ou interpretação do episódio.' };
  }

  function buildQuestionUtility() {
    const rows = [];
    Object.entries(stages).forEach(([stageKey, stage]) => {
      stage.imported.forEach((importedLabel) => {
        rows.push({
          stage: stage.label,
          question: importedLabel,
          role: 'Importar / não perguntar',
          roleModifier: 'is-imported',
          imported: true,
          seconds: 0,
          syntheticResponse: 'Preenchido nos bastidores',
          impact: 'Se perguntado novamente, aumenta tempo e redundância sem acrescentar informação.'
        });
      });
      stage.sections.forEach((section) => {
        section.questions.forEach((item) => {
          const classification = utilityClassification(item);
          rows.push({
            stage: stage.label,
            question: item.label,
            role: classification.label,
            roleModifier: classification.modifier,
            imported: false,
            seconds: item.seconds || 12,
            syntheticResponse: syntheticAnswer(stageKey, item),
            impact: classification.impact
          });
        });
      });
    });
    return rows;
  }

  function renderQuestionUtility() {
    const body = byId('sfa-lab-question-utility');
    if (!body) return;
    body.innerHTML = buildQuestionUtility().map((row) => `<tr>
      <td><strong>${escapeHtml(row.stage)}</strong></td>
      <td>${escapeHtml(row.question)}</td>
      <td><span class="sfa-lab__utility-role ${escapeHtml(row.roleModifier)}">${escapeHtml(row.role)}</span></td>
      <td>${row.imported ? 'Sim — SINAN/GAL/prontuário' : 'Não — complemento'}</td>
      <td class="small">${escapeHtml(row.syntheticResponse)}</td>
      <td>${row.seconds ? `${row.seconds} s` : '0 s'}</td>
      <td class="small">${escapeHtml(row.impact)}</td>
    </tr>`).join('');
  }

  function renderKpis(records, signals) {
    const incremental = signals.filter((signal) => !signal.sinanVisible).length;
    const linkedCases = signals.reduce((total, signal) => total + signal.directCases, 0);
    const active = signals.filter((signal) => signal.active).length;
    const discordant = records.filter((record) => record.recordedDiagnosis !== record.understoodDiagnosis).length;
    const decisions = registeredDecisions(signals).length;
    const t30 = records.filter((record) => record.t30Responded).length;
    const cards = [
      ['Participantes no T0', `${COHORT_SIZE}/${COHORT_SIZE}`, 'coorte fixa da simulação', false],
      ['Participantes no T30', `${t30}/${COHORT_SIZE}`, 'capacidade de encerrar o sinal', false],
      ['Sinais candidatos', String(signals.length), 'regra explícita; revisão humana', false],
      ['Sinais incrementais', String(incremental), 'não nomeáveis só com dados importados', true],
      ['Casos em vínculo específico', String(linkedCases), `de ${COHORT_SIZE} participantes (${percent(linkedCases, COHORT_SIZE)}%)`, false],
      ['Fontes possivelmente ativas', String(active), 'priorizam a verificação', true],
      ['Decisões concretas registradas', String(decisions), 'camada separada das sugestões', true],
      ['Divergências diagnósticas', String(discordant), 'entendido versus registrado', false]
    ];

    byId('sfa-lab-kpis').innerHTML = cards.map(([label, value, note, orange]) => `
      <div class="col-md-6 col-xl-3">
        <div class="sfa-lab__kpi ${orange ? 'is-orange' : ''}">
          <div class="sfa-lab__kpi-label">${escapeHtml(label)}</div>
          <div class="sfa-lab__kpi-value">${escapeHtml(value)}</div>
          <div class="sfa-lab__kpi-note">${escapeHtml(note)}</div>
        </div>
      </div>`).join('');
  }

  function renderCounterfactual(records, signals) {
    const baseSignals = signals.filter((signal) => signal.sinanVisible);
    const linkedCases = signals.reduce((total, signal) => total + signal.directCases, 0);
    const baseCases = baseSignals.reduce((total, signal) => total + signal.baseDirectCases, 0);
    const active = signals.filter((signal) => signal.active).length;
    const followed = signals.filter((signal) => signal.action).length;
    const baseDecisions = registeredDecisions(baseSignals).length;
    const decisions = registeredDecisions(signals).length;
    const rows = [
      ['Agrupamentos candidatos reconhecíveis', `${baseSignals.length} sinal(is)`, `${signals.length} sinal(is)`],
      ['Casos incluídos nos agrupamentos', `${baseCases} caso(s)`, `${linkedCases} caso(s)`],
      ['Fonte específica nomeável', 'não coletada neste conjunto', `${signals.length} fonte(s)`],
      ['Fontes ainda ativas informadas', 'não coletado neste conjunto', `${active} fonte(s)`],
      ['Sinais com orientação/ação percebida', 'não coletado neste conjunto', `${followed} sinal(is)`],
      ['Decisões administrativas ligadas aos sinais', `${baseDecisions} decisão(ões)`, `${decisions} decisão(ões)`]
    ];

    byId('sfa-lab-counterfactual').innerHTML = `<div class="sfa-lab__comparison">${rows.map(([title, base, added]) => `
      <div class="sfa-lab__comparison-row">
        <div class="sfa-lab__comparison-title">${escapeHtml(title)}</div>
        <div class="sfa-lab__comparison-cell"><small>Campos importados</small><strong>${escapeHtml(base)}</strong></div>
        <div class="sfa-lab__comparison-cell"><small>+ núcleo mínimo</small><strong>${escapeHtml(added)}</strong></div>
      </div>`).join('')}</div>
      <p class="small text-muted mt-3 mb-0">“Não coletado” significa indisponibilidade, não zero. Este é um contraste informacional sintético; não mede o desempenho global do SINAN nem prova ganho causal.</p>`;
  }

  function barRow(label, value, total, tone) {
    return `<div class="sfa-lab__bar-group">
      <div class="sfa-lab__bar-label"><span>${escapeHtml(label)}</span><strong>${value}/${total} (${percent(value, total)}%)</strong></div>
      <div class="sfa-lab__bar-track"><div class="sfa-lab__bar-fill ${tone || ''}" style="width:${percent(value, total)}%"></div></div>
    </div>`;
  }

  function renderFollowup(records) {
    const t10 = records.filter((record) => record.t10Responded).length;
    const t30 = records.filter((record) => record.t30Responded).length;
    byId('sfa-lab-followup').innerHTML = [
      barRow('T0', records.length, COHORT_SIZE, ''),
      barRow('T10', t10, COHORT_SIZE, 'is-orange'),
      barRow('T30', t30, COHORT_SIZE, 'is-muted')
    ].join('');
  }

  function renderDomains(records) {
    const counts = new Map();
    records.forEach((record) => {
      if (!record.exposureDomain) return;
      counts.set(record.exposureDomain, (counts.get(record.exposureDomain) || 0) + 1);
    });
    const entries = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...entries.map((entry) => entry[1]));
    byId('sfa-lab-domains').innerHTML = entries.length ? entries.map(([label, value], index) => `
      <div class="sfa-lab__bar-group">
        <div class="sfa-lab__bar-label"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>
        <div class="sfa-lab__bar-track"><div class="sfa-lab__bar-fill ${index === 1 ? 'is-orange' : index > 1 ? 'is-muted' : ''}" style="width:${Math.round((value / max) * 100)}%"></div></div>
      </div>`).join('') : '<div class="sfa-lab__empty">Nenhum domínio específico compartilhado neste cenário.</div>';
  }

  function renderSignals(signals) {
    const body = byId('sfa-lab-signals');
    const noSignals = byId('sfa-lab-no-signals');
    if (!signals.length) {
      body.innerHTML = '';
      noSignals.hidden = false;
      return;
    }
    noSignals.hidden = true;
    body.innerHTML = signals.map((signal) => {
      const decisions = signal.reviewStatus === 'accepted' && signal.actionable
        ? signal.decisions.filter((decision) => decision.attributedToReport)
        : [];
      return `<tr>
      <td><strong>${escapeHtml(signal.label)}</strong><div class="small text-muted">${escapeHtml(signal.domain)} · ${escapeHtml(signal.evidenceStrength)}</div></td>
      <td>${signal.directCases}${signal.reportedOthers
        ? `<div class="small text-muted">+ maior relato de ${signal.reportedOthers} coadoecido(s), sem deduplicação</div>`
        : ''}</td>
      <td>${escapeHtml(signal.stage)}<div class="small text-muted">cobertura ${escapeHtml(signal.stageCoverage)} · janela de triagem ${signal.windowDays} dias</div></td>
      <td><span class="sfa-lab__signal-status ${signal.statusClass}">${escapeHtml(signal.status)}</span>
        <div class="small text-muted mt-1">revisão: ${escapeHtml(signal.reviewStatus)}</div></td>
      <td class="small">${escapeHtml(signal.nextStep)}
        <div class="text-muted mt-1">${decisions.length
          ? `<strong>Decisões sintéticas registradas:</strong> ${decisions.map((decision) => escapeHtml(`${decision.id} — ${decision.label}`)).join('; ')}`
          : 'Nenhuma decisão registrada'}</div>
      </td>
    </tr>`;
    }).join('');
  }

  function renderAblation() {
    const kept = {};
    root.querySelectorAll('[data-ablation]').forEach((input) => {
      kept[input.dataset.ablation] = input.checked;
    });

    const ablatedRecords = state.cohort.map((record) => Object.assign({}, record, {
      exposureKey: kept.exposure ? record.exposureKey : null,
      specificity: kept.exposure ? record.specificity : 'none',
      exposurePlace: kept.place ? record.exposurePlace : null,
      exposureDateKnown: kept.date ? record.exposureDateKnown : false,
      linkComplete: Boolean(record.linkComplete && kept.exposure && kept.place && kept.date),
      sourceActiveT10: kept.active ? record.sourceActiveT10 : null,
      sourceStateT30: kept.active ? record.sourceStateT30 : null,
      t10Responded: kept.followup ? record.t10Responded : false,
      t30Responded: kept.followup ? record.t30Responded : false,
      actionObservedT30: kept.followup ? record.actionObservedT30 : false,
      postActionCases: kept.followup ? record.postActionCases : null
    }));
    const recalculatedSignals = buildSignals(ablatedRecords, reviewOverridesFor(state.currentScenarioKey));
    const recognizable = recalculatedSignals.length;
    const actionable = recalculatedSignals.filter((signal) => signal.actionable).length;
    const urgent = recalculatedSignals.filter((signal) => signal.actionable && signal.active).length;
    const closed = recalculatedSignals.filter((signal) => signal.actionable
      && (signal.finalSourceState === 'Aparentemente interrompida' || signal.action)).length;
    const decisions = registeredDecisions(recalculatedSignals)
      .filter((decision) => decision.requiredFields.every((field) => kept[field] !== false)).length;

    const result = byId('sfa-lab-ablation-result');
    result.innerHTML = `
      <strong>${recognizable}</strong><span>sinal(is) reconhecível(is)</span>
      <strong>${actionable}</strong><span>com informação mínima para ação</span>
      <strong>${urgent}</strong><span>com urgência qualificável</span>
      <strong>${closed}</strong><span>com seguimento de ação</span>
      <strong>${decisions}</strong><span>decisão(ões) rastreável(is) ao relatório</span>
      <small class="text-muted">Regra reaplicada aos ${COHORT_SIZE} registros sintéticos.</small>`;
  }

  function renderDataPreview(records) {
    const t10 = records.filter((record) => record.t10Responded).length;
    const t30 = records.filter((record) => record.t30Responded).length;
    const specific = records.filter((record) => record.specificity === 'specific').length;
    const discordant = records.filter((record) => record.recordedDiagnosis !== record.understoodDiagnosis).length;
    byId('sfa-lab-data-summary').innerHTML = [
      `${COHORT_SIZE} episódios no T0`, `${t10} linhas T10`, `${t30} linhas T30`,
      `${specific} vínculos específicos`, `${discordant} comparações diagnósticas divergentes`
    ].map((label) => `<span>${escapeHtml(label)}</span>`).join('');

    byId('sfa-lab-data-rows').innerHTML = records.slice(0, 10).map((record) => `<tr>
      <td><strong>${escapeHtml(record.id)}</strong></td>
      <td>dia ${record.onsetDay}</td>
      <td>${escapeHtml(record.neighborhood)}</td>
      <td>${escapeHtml(record.exposureLabel || 'Sem vínculo específico')}</td>
      <td>${record.t10Responded ? 'respondido' : 'ausente'}</td>
      <td>${record.t30Responded ? 'respondido' : 'ausente'}</td>
      <td>${record.recordedDiagnosis === record.understoodDiagnosis ? 'concordante' : 'divergente'}</td>
    </tr>`).join('');
  }

  function median(values) {
    if (!values.length) return 0;
    const ordered = values.slice().sort((a, b) => a - b);
    const middle = Math.floor(ordered.length / 2);
    return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
  }

  function renderDecisionRegistry(records, signals) {
    const decisions = registeredDecisions(signals);
    const body = byId('sfa-lab-decisions');
    const empty = byId('sfa-lab-no-decisions');
    if (!decisions.length) {
      body.innerHTML = '';
      empty.hidden = false;
    } else {
      empty.hidden = true;
      body.innerHTML = decisions.map((decision) => `<tr>
        <td><strong>${escapeHtml(decision.id)}</strong></td>
        <td>${escapeHtml(decision.signalLabel)}</td>
        <td>${escapeHtml(decision.label)}<div class="small text-muted">${escapeHtml(decision.owner)}</div></td>
        <td>dia ${decision.day}<div class="small text-muted">${escapeHtml(decision.status)}</div></td>
        <td>${escapeHtml(decision.reportContribution)}<div class="small text-muted">${decision.evidence.map(escapeHtml).join('; ')}</div></td>
        <td>${decision.peopleReached}<div class="small text-muted">registros, sem deduplicação</div></td>
      </tr>`).join('');
    }

    const totalDaysUnable = records.reduce((total, record) => total + record.daysUnable, 0);
    const medianExpense = median(records.map((record) => record.expense));
    const potentialExposures = signals.reduce((total, signal) => total + signal.potentialExposed, 0);
    const reached = decisions.reduce((total, decision) => total + decision.peopleReached, 0);
    const signalsWithDecision = new Set(decisions.map((decision) => decision.signalKey)).size;
    const decisionLag = decisions.length
      ? median(decisions.map((decision) => Math.max(0, decision.day - decision.earliestOnsetDay)))
      : null;
    const chips = [
      `${signalsWithDecision} sinal(is) geraram ≥1 decisão`,
      `${decisions.filter((decision) => decision.status === 'Executada').length} decisão(ões) executada(s)`,
      `${reached} registros de alcance, sem deduplicação`,
      `${potentialExposures} exposições potenciais relatadas, sem deduplicação`,
      `${totalDaysUnable} pessoa-dias sem atividade`,
      `gasto mediano sintético: R$ ${medianExpense.toFixed(2).replace('.', ',')}`
    ];
    if (decisionLag !== null) chips.push(`mediana de ${decisionLag} dia(s) até decisão`);
    byId('sfa-lab-secondary-metrics').innerHTML = chips.map((label) => `<span>${escapeHtml(label)}</span>`).join('');
  }

  function wilsonInterval(successes, total, z) {
    const p = successes / total;
    const z2 = z * z;
    const denominator = 1 + z2 / total;
    const center = (p + z2 / (2 * total)) / denominator;
    const margin = (z / denominator) * Math.sqrt((p * (1 - p) / total) + (z2 / (4 * total * total)));
    return [clamp(center - margin, 0, 1), clamp(center + margin, 0, 1)];
  }

  function syncPrecisionToCohort() {
    if (!state.cohort) return;
    const outcome = byId('sfa-lab-precision-outcome').value;
    let value = 0;
    if (outcome === 'completaram o T30') {
      value = state.cohort.filter((record) => record.t30Responded).length;
    } else if (outcome === 'forneceram um vínculo específico') {
      value = state.cohort.filter((record) => record.specificity === 'specific').length;
    } else {
      value = state.cohort.filter((record) => record.recordedDiagnosis !== record.understoodDiagnosis).length;
    }
    byId('sfa-lab-events').value = String(value);
    renderPrecision();
  }

  function renderPrecision() {
    const events = Number(byId('sfa-lab-events').value);
    const outcome = byId('sfa-lab-precision-outcome').value;
    const total = COHORT_SIZE;
    const estimate = events / total;
    const [low, high] = wilsonInterval(events, total, 1.96);
    const lowPct = Math.round(low * 1000) / 10;
    const highPct = Math.round(high * 1000) / 10;
    const estimatePct = Math.round(estimate * 1000) / 10;
    byId('sfa-lab-events-value').textContent = String(events);
    byId('sfa-lab-precision').innerHTML = `
      <div class="sfa-lab__precision-value">${estimatePct}%</div>
      <div class="small text-muted">estimativa sintética: ${events} de ${total} ${escapeHtml(outcome)}</div>
      <div class="sfa-lab__interval" aria-label="Intervalo de 95% entre ${lowPct}% e ${highPct}%">
        <span style="left:${lowPct}%;width:${Math.max(1, highPct - lowPct)}%"></span>
      </div>
      <strong>IC 95%: ${lowPct}% a ${highPct}%</strong>
      <p class="small text-muted mb-0 mt-2">A largura do intervalo é de ${(highPct - lowPct).toFixed(1)} pontos percentuais. O cálculo supõe observações independentes; não deve ser usado como inferência populacional para amostra de conveniência ou participantes do mesmo agrupamento.</p>`;
  }

  globalThis.__sfaLabModel = {
    cohortSize: COHORT_SIZE,
    stages,
    exampleAnswers,
    scenarioDefinitions,
    buildSyntheticCohort,
    buildSignals,
    registeredDecisions,
    buildFunnel,
    buildIalSummary,
    buildQuestionUtility,
    setSignalReview,
    acceptSignal,
    rejectSignal,
    reviewOverridesFor,
    wilsonInterval
  };

  const labTabs = Array.from(root.querySelectorAll('[data-lab-view]'));
  labTabs.forEach((button, index) => {
    button.addEventListener('click', () => switchView(button.dataset.labView));
    button.addEventListener('keydown', (event) => {
      let targetIndex = null;
      if (event.key === 'ArrowRight') targetIndex = (index + 1) % labTabs.length;
      if (event.key === 'ArrowLeft') targetIndex = (index - 1 + labTabs.length) % labTabs.length;
      if (event.key === 'Home') targetIndex = 0;
      if (event.key === 'End') targetIndex = labTabs.length - 1;
      if (targetIndex === null) return;
      event.preventDefault();
      labTabs[targetIndex].focus();
      switchView(labTabs[targetIndex].dataset.labView);
    });
  });

  root.querySelectorAll('.sfa-lab__stage-nav [data-stage]').forEach((button) => {
    button.addEventListener('click', () => switchStage(button.dataset.stage));
  });

  byId('sfa-lab-name').addEventListener('input', updateStageHeader);
  byId('sfa-lab-reset').addEventListener('click', () => {
    state.answers[state.stage] = {};
    state.stageStartedAt[state.stage] = Date.now();
    renderStage();
  });
  byId('sfa-lab-example').addEventListener('click', () => {
    state.answers[state.stage] = Object.assign({}, exampleAnswers[state.stage]);
    renderStage();
    byId('sfa-lab-announcer').textContent = `Exemplo da etapa ${stages[state.stage].label} preenchido.`;
  });
  byId('sfa-lab-next').addEventListener('click', () => {
    if (!validateCurrentStage()) return;
    if (state.stage === 't0') switchStage('t10');
    else if (state.stage === 't10') switchStage('t30');
    else switchView('cohort');
  });
  byId('sfa-lab-run-cohort').addEventListener('click', renderCohort);
  byId('sfa-lab-scenario').addEventListener('change', renderCohort);
  root.addEventListener('click', (event) => {
    const button = event.target.closest('[data-sfa-review-action][data-signal-key]');
    if (!button) return;
    setSignalReview(button.dataset.signalKey, button.dataset.sfaReviewAction, state.currentScenarioKey);
    renderCohort();
    byId('sfa-lab-announcer').textContent = button.dataset.sfaReviewAction === 'accepted'
      ? 'Correspondência aceita pela revisão humana simulada.'
      : 'Correspondência rejeitada pela revisão humana simulada.';
  });
  byId('sfa-lab-events').addEventListener('input', renderPrecision);
  byId('sfa-lab-precision-outcome').addEventListener('change', syncPrecisionToCohort);
  root.querySelectorAll('[data-ablation]').forEach((input) => {
    input.addEventListener('change', renderAblation);
  });

  renderStage();
  renderCohort();
  switchView(['participant', 'cohort', 'utility'].includes(root.dataset.initialView)
    ? root.dataset.initialView
    : 'participant');
  window.setInterval(updateTimeBadge, 1000);
})();
