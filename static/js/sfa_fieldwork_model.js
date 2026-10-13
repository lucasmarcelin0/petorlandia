(function () {
  'use strict';

  const BLOCKS_KEY = 'ento_fieldwork_blocks_v1';
  const VISITS_KEY = 'ento_fieldwork_visits_v1';
  const QUEUE_KEY = 'ento_fieldwork_queue_v1';

  function safeGet(key, def = {}) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : def;
    } catch (e) {
      console.warn('Erro ao ler do localStorage:', e);
      return def;
    }
  }

  function safeSet(key, val) {
    try {
      localStorage.setItem(key, JSON.stringify(val));
    } catch (e) {
      console.warn('Erro ao salvar no localStorage:', e);
    }
  }

  function uuid() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return 'v-' + Date.now().toString(36) + '-' + Math.random().toString(36).substring(2, 9);
  }

  const SfaFieldworkModel = {
    // ------------------------------------------------------------------------
    // Gestão de Quarteirões
    // ------------------------------------------------------------------------
    getBlocks() {
      return safeGet(BLOCKS_KEY, {});
    },

    saveBlock(setor, quarteirao, data) {
      const blocks = this.getBlocks();
      const key = `${setor}-${quarteirao}`;
      blocks[key] = {
        setor,
        quarteirao,
        cor: data.cor || blocks[key]?.cor || '',
        responsavel: data.responsavel || blocks[key]?.responsavel || '',
        status: data.status || blocks[key]?.status || 'PLANEJADO',
        atualizado_em: new Date().toISOString(),
        ...(blocks[key] || {}),
        ...data,
      };
      safeSet(BLOCKS_KEY, blocks);
      return blocks[key];
    },

    saveBlocksBatch(items) {
      const blocks = this.getBlocks();
      const now = new Date().toISOString();
      items.forEach(item => {
        const key = `${item.setor}-${item.quarteirao}`;
        blocks[key] = {
          ...(blocks[key] || {}),
          ...item,
          atualizado_em: now,
        };
      });
      safeSet(BLOCKS_KEY, blocks);
      return blocks;
    },

    // ------------------------------------------------------------------------
    // Gestão de Visitas Domiciliares (Offline-First)
    // ------------------------------------------------------------------------
    getVisits() {
      return safeGet(VISITS_KEY, []);
    },

    saveVisit(data) {
      const visits = this.getVisits();
      const queue = safeGet(QUEUE_KEY, []);
      const item = {
        uuid_local: data.uuid_local || uuid(),
        setor: String(data.setor || '').trim(),
        quarteirao: String(data.quarteirao || '').trim(),
        logradouro: data.logradouro || data.street || '',
        numero: data.numero || data.house_number || '',
        cnefe_id: data.cnefe_id || '',
        latitude: data.latitude != null ? Number(data.latitude) : null,
        longitude: data.longitude != null ? Number(data.longitude) : null,
        situacao: data.situacao || 'ABERTA',
        criadouros: Array.isArray(data.criadouros) ? data.criadouros : [],
        larvas: Boolean(data.larvas),
        tubitos: Number(data.tubitos || 0),
        agente: data.agente || '',
        data_visita: data.data_visita || new Date().toISOString().slice(0, 10),
        horario_visita: data.horario_visita || new Date().toISOString(),
        observacao: data.observacao || '',
        synced: false,
      };

      // Substitui se já existia visita para o mesmo cnefe_id/número na mesma data
      const idx = visits.findIndex(v => v.uuid_local === item.uuid_local ||
        (item.cnefe_id && v.cnefe_id === item.cnefe_id && v.data_visita === item.data_visita));

      if (idx >= 0) {
        visits[idx] = item;
      } else {
        visits.push(item);
      }
      safeSet(VISITS_KEY, visits);

      // Adiciona à fila de sincronização
      if (!queue.some(q => q.uuid_local === item.uuid_local)) {
        queue.push(item);
        safeSet(QUEUE_KEY, queue);
      }

      return item;
    },

    getPendingQueue() {
      return safeGet(QUEUE_KEY, []);
    },

    markSynced(uuids) {
      const set = new Set(uuids);
      const queue = safeGet(QUEUE_KEY, []).filter(q => !set.has(q.uuid_local));
      safeSet(QUEUE_KEY, queue);

      const visits = this.getVisits().map(v => set.has(v.uuid_local) ? { ...v, synced: true } : v);
      safeSet(VISITS_KEY, visits);
    },

    // ------------------------------------------------------------------------
    // Agregação & Métricas por Quarteirão
    // ------------------------------------------------------------------------
    summarizeBlock(setor, quarteirao, knownHousesCount) {
      const visits = this.getVisits().filter(v => v.setor === setor && v.quarteirao === quarteirao);
      const totalVisits = visits.length;
      const abertas = visits.filter(v => v.situacao === 'ABERTA').length;
      const fechadas = visits.filter(v => v.situacao === 'FECHADA').length;
      const recusas = visits.filter(v => v.situacao === 'RECUSA').length;
      const desabitados = visits.filter(v => v.situacao === 'DESABITADO').length;
      const larvas = visits.filter(v => v.larvas).length;

      const baseDenominator = Math.max(knownHousesCount || 0, totalVisits, 1);
      const pct = Math.min(100, Math.round((totalVisits / baseDenominator) * 100));

      return {
        totalKnown: knownHousesCount || totalVisits,
        totalVisits,
        abertas,
        fechadas,
        recusas,
        desabitados,
        larvas,
        pct,
        isCompleted: knownHousesCount > 0 && totalVisits >= knownHousesCount,
      };
    },

    // ------------------------------------------------------------------------
    // Gamificação do Agente
    // ------------------------------------------------------------------------
    computeGamification(visits, blocks) {
      const today = new Date().toISOString().slice(0, 10);
      const todayVisits = visits.filter(v => v.data_visita === today);

      let pontos = 0;
      let totalCriadouros = 0;
      let totalLarvas = 0;

      visits.forEach(v => {
        pontos += 10; // 10 pts por imóvel visitado
        const criadourosCount = (v.criadouros || []).length;
        totalCriadouros += criadourosCount;
        pontos += criadourosCount * 25; // 25 pts por criadouro inspecionado/tratado
        if (v.larvas) {
          totalLarvas++;
          pontos += 100; // 100 pts de bônus por foco de larva detectado e neutralizado
        }
      });

      // Bônus de quadras 100% concluídas
      const completedBlocks = Object.values(blocks).filter(b => b.status === 'TRABALHADO').length;
      pontos += completedBlocks * 250;

      // Nível do Agente
      const nivel = Math.max(1, Math.floor(pontos / 300) + 1);
      const titulos = [
        'Agente Aprendiz',
        'Sentinela do Bairro',
        'Guardião Comunitário',
        'Defensor de Orlândia',
        'Mestre da Vigilância',
      ];
      const tituloNivel = titulos[Math.min(nivel - 1, titulos.length - 1)];

      // Medalhas / Conquistas
      const badges = [];
      if (visits.length >= 1) {
        badges.push({ id: 'primeiro_passo', icon: '🌱', title: 'Primeiro Passo', desc: 'Primeiro imóvel visitado!' });
      }
      if (todayVisits.length >= 20) {
        badges.push({ id: 'ritmo_forte', icon: '⚡', title: 'Ritmo Forte', desc: 'Mais de 20 visitas hoje!' });
      }
      if (totalLarvas >= 1) {
        badges.push({ id: 'olho_de_lince', icon: '🎯', title: 'Olho de Lince', desc: 'Foco de larvas neutralizado!' });
      }
      if (completedBlocks >= 1) {
        badges.push({ id: 'quadra_fechada', icon: '🏆', title: 'Mestre da Quadra', desc: 'Quarteirão 100% concluído!' });
      }
      if (visits.length >= 50) {
        badges.push({ id: 'escudo_de_ouro', icon: '🛡️', title: 'Escudo de Orlândia', desc: 'Mais de 50 imóveis protegidos!' });
      }

      return {
        pontos,
        nivel,
        tituloNivel,
        todayCount: todayVisits.length,
        totalVisits: visits.length,
        totalCriadouros,
        totalLarvas,
        completedBlocks,
        badges,
        familiasProtegidas: Math.round(visits.length * 3.2), // estimativa média de moradores
      };
    },

    // ------------------------------------------------------------------------
    // Exportação em CSV
    // ------------------------------------------------------------------------
    toCSV(visits) {
      const headers = [
        'Data', 'Horario', 'Setor', 'Quarteirao', 'Logradouro', 'Numero',
        'Situacao', 'Criadouros_Agua', 'Larvas_Presentes', 'Quantidade_Tubitos',
        'Agente', 'Observacao', 'UUID'
      ];
      const rows = visits.map(v => [
        v.data_visita || '',
        v.horario_visita ? v.horario_visita.slice(11, 19) : '',
        v.setor || '',
        v.quarteirao || '',
        (v.logradouro || '').replace(/;/g, ','),
        v.numero || '',
        v.situacao || '',
        (v.criadouros || []).join(','),
        v.larvas ? 'SIM' : 'NAO',
        v.tubitos || 0,
        (v.agente || '').replace(/;/g, ','),
        (v.observacao || '').replace(/;/g, ','),
        v.uuid_local || '',
      ]);
      return [headers.join(';'), ...rows.map(r => r.join(';'))].join('\r\n');
    },
  };

  if (typeof window !== 'undefined') {
    window.SfaFieldworkModel = SfaFieldworkModel;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = SfaFieldworkModel;
  }
})();
