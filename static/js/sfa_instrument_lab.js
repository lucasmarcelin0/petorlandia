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
            question('similar_count', 'Aproximadamente quantas pessoas?', 'number', [], {
              conditional: true, showWhen: (a) => a.similar_cases === 'Sim', min: 1, max: 99
            }),
            question('shared_setting', 'O que essas pessoas podem ter compartilhado?', 'checkboxes', [
              'Casa', 'Vizinhança', 'Trabalho', 'Escola', 'Serviço de saúde', 'Refeição ou alimento',
              'Evento', 'Viagem ou transporte', 'Atividade com animais', 'Outro'
            ], { conditional: true, showWhen: (a) => a.similar_cases === 'Sim' }),
            question('cluster_where', 'Onde ocorreu esse possível vínculo?', 'text', [], {
              conditional: true, showWhen: (a) => a.similar_cases === 'Sim',
              placeholder: 'Nome do local, estabelecimento, propriedade ou referência'
            }),
            question('cluster_timing', 'Os sintomas das outras pessoas começaram quando?', 'radio', ['Antes dos seus', 'Na mesma época', 'Depois dos seus', 'Não sei'], {
              conditional: true, showWhen: (a) => a.similar_cases === 'Sim'
            }),
            question('cluster_suspected', 'Qual exposição em comum você suspeita?', 'text', [], {
              conditional: true, showWhen: (a) => a.similar_cases === 'Sim',
              placeholder: 'Produto, alimento, animal, local, atividade ou evento'
            })
          ]
        },
        {
          title: 'Ambiente e deslocamentos', icon: 'fa-tree', questions: [
            question('environment', 'Nos 15 dias antes dos sintomas, houve alguma destas situações?', 'checkboxes', [
              'Água suja, lama, enchente ou esgoto', 'Rio, córrego, pesca ou natação', 'Mata, trilha, pasto ou camping',
              'Chácara, fazenda ou área rural', 'Muitos mosquitos, carrapatos ou outros vetores',
              'Viagem ou permanência em outro município', 'Nenhuma destas situações'
            ], { exclusive: ['Nenhuma destas situações'] }),
            question('environment_detail', 'Onde e em qual data ou período?', 'text', [], {
              conditional: true,
              showWhen: (a) => hasPositiveSelection(a.environment, 'Nenhuma destas situações'),
              placeholder: 'Local + data aproximada'
            }),
            question('environment_others', 'Outras pessoas expostas nesse local também adoeceram?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true,
              showWhen: (a) => hasPositiveSelection(a.environment, 'Nenhuma destas situações')
            })
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
            question('animal_detail', 'Qual animal, o que ocorreu, onde e quando?', 'textarea', [], {
              conditional: true,
              showWhen: (a) => hasPositiveSelection(a.animal, 'Nenhum evento animal relevante'),
              placeholder: 'Espécie + evento + local + data aproximada'
            }),
            question('animal_others', 'Outros animais ou pessoas ligados ao evento adoeceram?', 'radio', ['Não', 'Sim', 'Não sei'], {
              conditional: true,
              showWhen: (a) => hasPositiveSelection(a.animal, 'Nenhum evento animal relevante')
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
            ], { exclusive: ['Nenhuma destas exposições'] }),
            question('food_item', 'Qual alimento, água ou produto?', 'text', [], {
              conditional: true, showWhen: (a) => hasPositiveSelection(a.food, 'Nenhuma destas exposições'),
              placeholder: 'Nome específico do item'
            }),
            question('food_origin', 'Marca, produtor, origem ou local de compra/consumo', 'text', [], {
              conditional: true, showWhen: (a) => hasPositiveSelection(a.food, 'Nenhuma destas exposições')
            }),
            question('food_date', 'Data aproximada do consumo ou contato', 'date', [], {
              conditional: true, showWhen: (a) => hasPositiveSelection(a.food, 'Nenhuma destas exposições')
            }),
            question('food_people', 'Quantas pessoas consumiram e quantas adoeceram?', 'text', [], {
              conditional: true, showWhen: (a) => hasPositiveSelection(a.food, 'Nenhuma destas exposições'),
              placeholder: 'Ex.: 8 consumiram; 4 adoeceram'
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
            question('lost_income_any', 'Houve perda de renda desde o T0?', 'radio', ['Não', 'Sim']),
            question('lost_income', 'Valor aproximado da perda de renda (R$)', 'number', [], {
              conditional: true, showWhen: (a) => a.lost_income_any === 'Sim', min: 0, max: 99999, step: '0.01'
            })
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
            question('lost_income_any', 'Houve nova perda de renda desde o último contato?', 'radio', ['Não', 'Sim']),
            question('lost_income', 'Valor aproximado da nova perda de renda (R$)', 'number', [], {
              conditional: true, showWhen: (a) => a.lost_income_any === 'Sim', min: 0, max: 99999, step: '0.01'
            })
          ]
        }
      ]
    }
  };

  const exampleAnswers = {
    t0: {
      respondent_role: 'A própria pessoa',
      consent: ['Li o TCLE e aceito participar voluntariamente.'],
      similar_cases: 'Sim', similar_count: '3', shared_setting: ['Refeição ou alimento'],
      cluster_where: 'Feira Central de Orlândia', cluster_timing: 'Na mesma época',
      cluster_suspected: 'Queijo fresco comprado na mesma banca',
      environment: ['Nenhuma destas situações'], animal: ['Nenhum evento animal relevante'],
      food: ['Leite cru ou queijo sem inspeção', 'Outras pessoas que consumiram também adoeceram'],
      food_item: 'Queijo fresco', food_origin: 'Banca da Feira Central', food_date: '2026-08-21',
      food_people: '7 consumiram; 4 adoeceram', extra_symptoms: ['Diarreia'],
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
    signals: []
  };

  function hasPositiveSelection(value, negativeLabel) {
    return Array.isArray(value) && value.length > 0 && !value.includes(negativeLabel);
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
      nextButton.innerHTML = 'Ver a coorte de 50 <i class="fas fa-chart-column ms-1" aria-hidden="true"></i>';
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
      description: 'Três vínculos específicos coexistem; dois não seriam nomeáveis apenas com os campos importados. O seguimento informa fonte ativa e ação percebida.',
      t10Count: 43,
      t30Count: 38,
      clusters: [
        {
          key: 'food:queijo-feira-central', label: 'Queijo fresco — Feira Central', domain: 'Alimento/água/produto',
          size: 7, onsetStart: 3, onsetSpan: 4, location: 'Feira Central', potentialExposed: 24,
          sinanVisible: false, active: true, sourceStateT30: 'Aparentemente interrompida',
          action: true, postActionCases: false, discoverAt: 'T0', windowDays: 7,
          decisions: [
            simulatedDecision('D-SIM-001', 'Inspeção do ponto de venda', 8, 'Executada', 'Vigilância Sanitária', 'Principal', ['T0: item/origem', 'T10: fonte ativa'], ['exposure', 'place', 'date', 'followup'], 7),
            simulatedDecision('D-SIM-002', 'Orientação aos coexpostos', 9, 'Executada', 'Vigilância Epidemiológica', 'Principal', ['T0: coadoecidos', 'T10: pessoas expostas'], ['exposure', 'place', 'followup', 'active'], 18),
            simulatedDecision('D-SIM-003', 'Rastreio da origem do produto', 10, 'Em andamento', 'Vigilância Sanitária', 'Contributiva', ['T0: marca/origem/local'], ['exposure', 'place', 'date'], 1)
          ]
        },
        {
          key: 'animal:fazenda-santa-clara', label: 'Carrapatos — Fazenda Santa Clara', domain: 'Animal/rural',
          size: 5, onsetStart: 11, onsetSpan: 4, location: 'Fazenda Santa Clara', potentialExposed: 9,
          sinanVisible: false, active: true, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 14,
          decisions: [
            simulatedDecision('D-SIM-004', 'Articulação para verificação One Health', 16, 'Registrada', 'Vigilância Epidemiológica', 'Contributiva', ['T0: evento animal e propriedade'], ['exposure', 'place'], 5)
          ]
        },
        {
          key: 'event:escola-aurora', label: 'Evento — Escola Municipal Aurora', domain: 'Trabalho/escola/evento',
          size: 4, onsetStart: 20, onsetSpan: 3, location: 'Escola Municipal Aurora', potentialExposed: 18,
          sinanVisible: true, active: false, sourceStateT30: 'Aparentemente interrompida',
          action: true, postActionCases: false, discoverAt: 'T10', windowDays: 7,
          decisions: [
            simulatedDecision('D-SIM-005', 'Contato com a instituição', 24, 'Executada', 'Vigilância Epidemiológica', 'Contributiva', ['SINAN: tempo/território', 'T10: evento específico'], ['exposure', 'place', 'followup'], 4),
            simulatedDecision('D-SIM-006', 'Orientação ao grupo exposto', 25, 'Executada', 'Vigilância Epidemiológica', 'Contributiva', ['T10: instituição e coexpostos'], ['exposure', 'place', 'followup'], 18)
          ]
        }
      ]
    },
    sporadic: {
      description: 'Exposições variadas e pouco específicas, sem duas pessoas diretamente ligadas à mesma fonte. O resultado honesto é não abrir uma fila artificial de sinais.',
      t10Count: 42,
      t30Count: 37,
      clusters: []
    },
    attrition: {
      description: 'Dois vínculos surgem no T0, mas apenas 29 pessoas respondem ao T10 e 20 ao T30. A detecção permanece; urgência e encerramento ficam incompletos.',
      t10Count: 29,
      t30Count: 20,
      clusters: [
        {
          key: 'water:corrego-bebedouro', label: 'Água — córrego próximo ao bebedouro', domain: 'Ambiente/água',
          size: 6, onsetStart: 6, onsetSpan: 4, location: 'Zona rural norte', potentialExposed: 15,
          sinanVisible: false, active: true, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 14,
          decisions: []
        },
        {
          key: 'food:lanche-evento', label: 'Lanche — evento comunitário', domain: 'Alimento/água/produto',
          size: 4, onsetStart: 18, onsetSpan: 3, location: 'Centro comunitário', potentialExposed: 30,
          sinanVisible: true, active: null, sourceStateT30: 'Desconhecida',
          action: false, postActionCases: null, discoverAt: 'T0', windowDays: 7,
          decisions: []
        }
      ]
    }
  };

  function responseSelected(index, count, salt) {
    return ((index * 17 + salt) % 50) < count;
  }

  function buildSyntheticCohort(scenarioKey) {
    const scenario = scenarioDefinitions[scenarioKey];
    const assignments = new Map();
    let cursor = 0;
    scenario.clusters.forEach((cluster) => {
      for (let within = 0; within < cluster.size && cursor < 50; within += 1) {
        assignments.set(cursor, { cluster, within });
        cursor += 1;
      }
    });

    const neighborhoods = ['Centro', 'Jardim Boa Vista', 'Vila Bucci', 'Jardim Teixeira', 'Zona rural'];
    const diagnoses = ['Dengue', 'Sem definição', 'Dengue', 'Chikungunya', 'Sem definição'];
    const broadDomains = ['Ambiente/água', 'Animal/rural', 'Alimento/água/produto', 'Trabalho/escola/evento'];
    const participantIndexes = Array.from({ length: 50 }, (_, index) => index);
    const t10Indexes = participantIndexes.filter((index) => responseSelected(index, scenario.t10Count, 7));
    const t10Set = new Set(t10Indexes);
    const t30Set = new Set(t10Indexes
      .slice()
      .sort((a, b) => (((a * 23) + 13) % 101) - (((b * 23) + 13) % 101))
      .slice(0, scenario.t30Count));

    return Array.from({ length: 50 }, (_, index) => {
      const assigned = assignments.get(index);
      const cluster = assigned ? assigned.cluster : null;
      const t10Responded = t10Set.has(index);
      const t30Responded = t30Set.has(index);
      const recordedDiagnosis = diagnoses[index % diagnoses.length];
      const understoodDiagnosis = index % 6 === 0
        ? (recordedDiagnosis === 'Dengue' ? 'Virose/indefinida' : 'Dengue')
        : recordedDiagnosis;
      const hasBroadExposure = !cluster && index % 8 === 0;

      return {
        id: `P${String(index + 1).padStart(3, '0')}`,
        onsetDay: cluster ? cluster.onsetStart + (assigned.within % cluster.onsetSpan) : 1 + ((index * 7) % 30),
        neighborhood: cluster ? cluster.location : neighborhoods[index % neighborhoods.length],
        exposureKey: cluster ? cluster.key : (hasBroadExposure ? `broad:${index}` : null),
        exposureLabel: cluster ? cluster.label : (hasBroadExposure ? 'Exposição inespecífica isolada' : null),
        exposureDomain: cluster ? cluster.domain : (hasBroadExposure ? broadDomains[index % broadDomains.length] : null),
        specificity: cluster ? 'specific' : (hasBroadExposure ? 'broad' : 'none'),
        exposurePlace: cluster ? cluster.location : null,
        exposureDateKnown: Boolean(cluster),
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
        sinanVisible: Boolean(cluster && cluster.sinanVisible),
        potentialExposed: cluster ? cluster.potentialExposed : 0,
        recordedDiagnosis,
        understoodDiagnosis,
        daysUnable: 1 + ((index * 3) % 7),
        expense: index % 4 === 0 ? 0 : 25 + ((index * 19) % 180)
      };
    });
  }

  function buildSignals(records) {
    const grouped = new Map();
    records.forEach((record) => {
      if (!record.exposureKey || record.specificity !== 'specific') return;
      if (!grouped.has(record.exposureKey)) grouped.set(record.exposureKey, []);
      grouped.get(record.exposureKey).push(record);
    });

    return Array.from(grouped.values()).map((group) => {
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
        key: first.exposureKey,
        label: first.exposureLabel,
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
        actionable: Boolean(first.exposurePlace) && available.every((record) => record.exposureDateKnown),
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
      'Trabalho/escola/evento': 'Contatar instituição e avaliar busca/orientação'
    };
    return steps[domain] || 'Revisar vínculo, tempo e local';
  }

  function renderCohort() {
    const scenarioKey = byId('sfa-lab-scenario').value;
    const scenario = scenarioDefinitions[scenarioKey];
    state.cohort = buildSyntheticCohort(scenarioKey);
    state.signals = buildSignals(state.cohort);
    byId('sfa-lab-scenario-description').textContent = scenario.description;

    renderKpis(state.cohort, state.signals);
    renderCounterfactual(state.cohort, state.signals);
    renderFollowup(state.cohort);
    renderDomains(state.cohort);
    renderSignals(state.signals);
    renderDataPreview(state.cohort);
    renderDecisionRegistry(state.cohort, state.signals);
    renderAblation();
    syncPrecisionToCohort();
  }

  function registeredDecisions(signals) {
    return signals.flatMap((signal) => (signal.decisions || [])
      .filter((decision) => decision.attributedToReport)
      .map((decision) => Object.assign({ signalKey: signal.key, signalLabel: signal.label, earliestOnsetDay: signal.earliestOnsetDay }, decision)));
  }

  function renderKpis(records, signals) {
    const incremental = signals.filter((signal) => !signal.sinanVisible).length;
    const linkedCases = signals.reduce((total, signal) => total + signal.directCases, 0);
    const active = signals.filter((signal) => signal.active).length;
    const discordant = records.filter((record) => record.recordedDiagnosis !== record.understoodDiagnosis).length;
    const decisions = registeredDecisions(signals).length;
    const t30 = records.filter((record) => record.t30Responded).length;
    const cards = [
      ['Participantes no T0', '50/50', 'coorte fixa da simulação', false],
      ['Participantes no T30', `${t30}/50`, 'capacidade de encerrar o sinal', false],
      ['Sinais candidatos', String(signals.length), 'regra explícita; revisão humana', false],
      ['Sinais incrementais', String(incremental), 'não nomeáveis só com dados importados', true],
      ['Casos em vínculo específico', String(linkedCases), `de 50 participantes (${percent(linkedCases, 50)}%)`, false],
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
      barRow('T0', records.length, 50, ''),
      barRow('T10', t10, 50, 'is-orange'),
      barRow('T30', t30, 50, 'is-muted')
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
      const decisions = signal.decisions.filter((decision) => decision.attributedToReport);
      return `<tr>
      <td><strong>${escapeHtml(signal.label)}</strong><div class="small text-muted">${escapeHtml(signal.domain)} · ${escapeHtml(signal.evidenceStrength)}</div></td>
      <td>${signal.directCases}${signal.reportedOthers
        ? `<div class="small text-muted">+ maior relato de ${signal.reportedOthers} coadoecido(s), sem deduplicação</div>`
        : ''}</td>
      <td>${escapeHtml(signal.stage)}<div class="small text-muted">cobertura ${escapeHtml(signal.stageCoverage)} · janela de triagem ${signal.windowDays} dias</div></td>
      <td><span class="sfa-lab__signal-status ${signal.statusClass}">${escapeHtml(signal.status)}</span></td>
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
      sourceActiveT10: kept.active ? record.sourceActiveT10 : null,
      sourceStateT30: kept.active ? record.sourceStateT30 : null,
      t10Responded: kept.followup ? record.t10Responded : false,
      t30Responded: kept.followup ? record.t30Responded : false,
      actionObservedT30: kept.followup ? record.actionObservedT30 : false,
      postActionCases: kept.followup ? record.postActionCases : null
    }));
    const recalculatedSignals = buildSignals(ablatedRecords);
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
      <small class="text-muted">Regra reaplicada aos 50 registros sintéticos.</small>`;
  }

  function renderDataPreview(records) {
    const t10 = records.filter((record) => record.t10Responded).length;
    const t30 = records.filter((record) => record.t30Responded).length;
    const specific = records.filter((record) => record.specificity === 'specific').length;
    const discordant = records.filter((record) => record.recordedDiagnosis !== record.understoodDiagnosis).length;
    byId('sfa-lab-data-summary').innerHTML = [
      `50 episódios no T0`, `${t10} linhas T10`, `${t30} linhas T30`,
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
    const total = 50;
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
  byId('sfa-lab-events').addEventListener('input', renderPrecision);
  byId('sfa-lab-precision-outcome').addEventListener('change', syncPrecisionToCohort);
  root.querySelectorAll('[data-ablation]').forEach((input) => {
    input.addEventListener('change', renderAblation);
  });

  renderStage();
  renderCohort();
  window.setInterval(updateTimeBadge, 1000);
})();
