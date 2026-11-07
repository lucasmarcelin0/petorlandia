// Regras do protótipo iReverse (certificadora de créditos de logística reversa).
// Uso: node tests/test_ireverse_core.js
// Fuso do Brasil: o "hoje" do protótipo não pode virar amanhã depois das 21h.
process.env.TZ = 'America/Sao_Paulo';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const path = require('node:path');

const C = require(path.join(__dirname, '..', 'static', 'easter_egg', 'ireverse-core.js'));

// ── SHA-256 próprio confere com o do Node ──────────────────────────────────
for (const txt of ['', 'abc', 'a'.repeat(1000), 'ação ✓ logística reversa']) {
  assert.equal(C.sha256(txt), crypto.createHash('sha256').update(txt).digest('hex'));
}

// ── Documentos ─────────────────────────────────────────────────────────────
assert.ok(C.validarCNPJ('11.222.333/0001-81'));
assert.ok(!C.validarCNPJ('11.222.333/0001-82'));
assert.ok(C.validarCNPJ('12.ABC.345/01DE-35'), 'CNPJ alfanumérico (IN RFB 2.229/2024)');
assert.ok(C.validarCPF('529.982.247-25'));
assert.ok(!C.validarCPF('111.111.111-11'));
assert.equal(C.mascararDoc('52998224725'), '***.982.247-**');

const chave = C.gerarChave({ uf: 'SP', ano: 2026, mes: 3, cnpj: '11222333000181', numero: 42 });
assert.equal(chave.length, 44);
assert.ok(C.analisarChave(chave).valida);
assert.ok(!C.analisarChave(chave.slice(0, 43) + ((Number(chave[43]) + 1) % 10)).valida, 'DV adulterado');
assert.ok(!C.analisarChave(chave.replace('55001', '65001')).valida, 'NFC-e não serve');
assert.ok(C.analisarChave(C.gerarChave({ uf: 'SP', ano: 2026, mes: 8, cnpj: '12ABC34501DE35' })).valida);

// ── Cenário completo da cadeia ─────────────────────────────────────────────
let relogio = new Date('2026-10-01T12:00:00Z');
const reg = new C.Registro({ agora: () => relogio });
const ok = (r) => { assert.ok(r.ok, JSON.stringify(r.erros)); return r; };
const falha = (r, trecho) => {
  assert.ok(!r.ok, 'deveria ter sido bloqueado: ' + trecho);
  assert.ok(r.erros.join(' ').includes(trecho), `esperava "${trecho}" em ${JSON.stringify(r.erros)}`);
};

const cnpj = (n) => C.gerarCNPJ(String(n).padStart(8, '0') + '0001');
const coop = ok(reg.cadastrarParticipante({ tipo: 'cooperativa', nome: 'Coop Recicla', doc: cnpj(10000001), uf: 'SP' })).id;
const catador = ok(reg.cadastrarParticipante({ tipo: 'catador', nome: 'Maria Catadora', doc: C.gerarCPF('123456789'), uf: 'SP' })).id;
const ferro = ok(reg.cadastrarParticipante({ tipo: 'atacadista', nome: 'Ferro-Velho Central', doc: cnpj(20000002), uf: 'SP' })).id;
const recic = ok(reg.cadastrarParticipante({ tipo: 'reciclador', nome: 'Recicladora Paulista', doc: cnpj(30000003), uf: 'SP', capacidadeKgMes: 50000 })).id;
const entidade = ok(reg.cadastrarParticipante({ tipo: 'entidade', nome: 'Entidade Gestora', doc: cnpj(40000004), uf: 'SP' })).id;
const verif = ok(reg.cadastrarParticipante({ tipo: 'verificador', nome: 'Verificadora Independente', doc: cnpj(50000005), uf: 'SP' })).id;
const empresa = ok(reg.cadastrarParticipante({ tipo: 'empresa', nome: 'Bebidas SA', doc: cnpj(60000006), uf: 'SP' })).id;

// Conflito de interesses: filial da entidade gestora não pode ser verificador.
falha(reg.cadastrarParticipante({ tipo: 'verificador', nome: 'Filial', doc: C.gerarCNPJ('400000040002'), uf: 'SP' }), 'Conflito de interesses');
falha(reg.cadastrarParticipante({ tipo: 'cooperativa', nome: 'Repetida', doc: cnpj(10000001), uf: 'SP' }), 'já está cadastrado');

const doc = (id) => reg.participante(id).doc;
const nfCoop = C.gerarChave({ uf: 'SP', ano: 2026, mes: 2, cnpj: doc(coop), numero: 1 });
const nfCoopDireta = C.gerarChave({ uf: 'SP', ano: 2026, mes: 3, cnpj: doc(coop), numero: 2 });
const nfFerro = C.gerarChave({ uf: 'SP', ano: 2026, mes: 4, cnpj: doc(ferro), numero: 10 });
const nfAntiga = C.gerarChave({ uf: 'SP', ano: 2024, mes: 5, cnpj: doc(coop), numero: 3 });

// Cooperativa vende 1.000 kg ao ferro-velho e 500 kg direto à recicladora.
ok(reg.registrarNFe(coop, { chave: nfCoop, emitenteId: coop, destinatarioId: ferro, material: 'plastico', massaKg: 1000, dataEmissao: '2026-02-10' }));
ok(reg.registrarNFe(coop, { chave: nfCoopDireta, emitenteId: coop, destinatarioId: recic, material: 'plastico', massaKg: 500, dataEmissao: '2026-03-05' }));

// Unicidade: a mesma chave não entra duas vezes.
falha(reg.registrarNFe(coop, { chave: nfCoop, emitenteId: coop, destinatarioId: ferro, material: 'plastico', massaKg: 1000, dataEmissao: '2026-02-10' }), 'Dupla contagem bloqueada');
// Nota de terceiro: o CNPJ da chave não é do emitente.
falha(reg.registrarNFe(ferro, { chave: C.gerarChave({ uf: 'SP', ano: 2026, mes: 4, cnpj: doc(coop), numero: 99 }), emitenteId: ferro, destinatarioId: recic, material: 'plastico', massaKg: 10, dataEmissao: '2026-04-01' }), 'não é o do emitente');
// Data divergente da chave.
falha(reg.registrarNFe(coop, { chave: C.gerarChave({ uf: 'SP', ano: 2026, mes: 6, cnpj: doc(coop), numero: 98 }), emitenteId: coop, destinatarioId: recic, material: 'plastico', massaKg: 10, dataEmissao: '2026-07-01' }), 'não bate');
// Atacadista só vale vendendo a recicladora (art. 15 §8º): aqui o destino é uma cooperativa, que nem recebe.
falha(reg.registrarNFe(ferro, { chave: C.gerarChave({ uf: 'SP', ano: 2026, mes: 4, cnpj: doc(ferro), numero: 97 }), emitenteId: ferro, destinatarioId: coop, material: 'plastico', massaKg: 10, dataEmissao: '2026-04-01' }), 'recicladora');
// Ferro-velho tentando repassar mais do que comprou da cooperativa.
falha(reg.registrarNFe(ferro, { chave: nfFerro, emitenteId: ferro, destinatarioId: recic, material: 'plastico', massaKg: 1500, dataEmissao: '2026-04-02', origens: [{ chave: nfCoop, massaKg: 1200 }] }), 'Não colidência');

// Ferro-velho revende 1.200 kg: 1.000 kg vieram da cooperativa (rastreados) + 200 kg próprios.
const revenda = ok(reg.registrarNFe(ferro, { chave: nfFerro, emitenteId: ferro, destinatarioId: recic, material: 'plastico', massaKg: 1200, dataEmissao: '2026-04-02', origens: [{ chave: nfCoop, massaKg: 1000 }] }));
assert.equal(revenda.alertas.length, 0);
// A mesma nota de origem não pode ser repassada de novo em outra revenda.
falha(reg.registrarNFe(ferro, { chave: C.gerarChave({ uf: 'SP', ano: 2026, mes: 4, cnpj: doc(ferro), numero: 11 }), emitenteId: ferro, destinatarioId: recic, material: 'plastico', massaKg: 300, dataEmissao: '2026-04-03', origens: [{ chave: nfCoop, massaKg: 100 }] }), 'Não colidência');

// Homologar exige o CDF da recicladora antes.
falha(reg.homologarNFe(verif, nfFerro, 'autorizada'), 'destinação final');
// Só a recicladora destinatária confirma; o ferro-velho não pode.
falha(reg.confirmarRecebimento(ferro, nfFerro, { mtr: 'MTR-1', cdf: 'CDF-1', massaRecebidaKg: 1200, data: '2026-04-03' }), 'indústria recicladora');
// Recebeu 1.140 kg (perda de 5%): só a massa recebida vira crédito, proporcional.
ok(reg.confirmarRecebimento(recic, nfFerro, { mtr: 'MTR-2026-0001', cdf: 'CDF-2026-0001', massaRecebidaKg: 1140, data: '2026-04-03' }));
falha(reg.confirmarRecebimento(recic, nfCoopDireta, { mtr: 'MTR-2026-0001', cdf: 'CDF-2026-0002', massaRecebidaKg: 500, data: '2026-03-06' }), 'Este MTR já comprovou');
ok(reg.confirmarRecebimento(recic, nfCoopDireta, { mtr: 'MTR-2026-0002', cdf: 'CDF-2026-0002', massaRecebidaKg: 500, data: '2026-03-06' }));

// A entidade gestora não homologa: só o verificador independente.
falha(reg.homologarNFe(entidade, nfFerro, 'autorizada'), 'verificador de resultados');
falha(reg.homologarNFe(verif, nfFerro, 'pendente'), 'SEFAZ');
ok(reg.homologarNFe(verif, nfFerro, 'autorizada'));
ok(reg.homologarNFe(verif, nfCoopDireta, 'autorizada'));

let m = reg.massas();
// Origem ainda não homologada: crédito da cooperativa fica pendente, nunca vai para o ferro-velho.
assert.equal(m[nfFerro].elegivelG, 190000, 'ferro-velho: 200 kg × 1140/1200');
assert.equal(m[nfCoop].elegivelG, 0);
assert.equal(m[nfCoop].pendenteG, 950000);
ok(reg.homologarNFe(verif, nfCoop, 'autorizada'));
m = reg.massas();
assert.equal(m[nfCoop].elegivelG, 950000, 'cooperativa: 1000 kg × 1140/1200');
// Cada quilo recebido é contado uma vez só: 1.140 + 500.
const totalElegivel = Object.values(m).reduce((s, x) => s + x.elegivelG, 0);
assert.equal(totalElegivel, 1640000);

// Emissão: só a entidade gestora, e a prioridade é das organizações de catadores.
falha(reg.emitirCertificado(verif, { empresaId: empresa, material: 'plastico', anoMeta: 2026, massaKg: 100 }), 'entidade gestora');
falha(reg.emitirCertificado(entidade, { empresaId: empresa, material: 'plastico', anoMeta: 2026, massaKg: 2000 }), 'Lastro insuficiente');
const c1 = ok(reg.emitirCertificado(entidade, { empresaId: empresa, material: 'plastico', anoMeta: 2026, massaKg: 1500 }));
const cert1 = reg.consultarCertificado(c1.codigo);
assert.deepEqual(cert1.lastro.map((l) => l.chave), [nfCoop, nfCoopDireta, nfFerro]);
assert.equal(cert1.catadoresG, 1450000, 'cooperativa esgotada antes do ferro-velho');
assert.equal(reg.massas()[nfFerro].saldoG, 140000);
falha(reg.emitirCertificado(entidade, { empresaId: empresa, material: 'plastico', anoMeta: 2026, massaKg: 141 }), 'Lastro insuficiente');

// Não rejeita nota que já lastreia certificado.
falha(reg.rejeitarNFe(verif, nfCoopDireta, 'NF cancelada na SEFAZ'), 'Cancele-os primeiro');

// Baixa: um certificado comprova uma meta, uma única vez, em um único sistema.
falha(reg.aposentarCertificado(entidade, c1.codigo, { sistema: '' }), 'Informe em qual sistema');
ok(reg.aposentarCertificado(empresa, c1.codigo, { sistema: 'SINIR / Sisrev-BR', protocolo: 'REL-2026-1' }));
falha(reg.aposentarCertificado(empresa, c1.codigo, { sistema: 'CETESB' }), 'Não pode ser usado de novo');
falha(reg.cancelarCertificado(entidade, c1.codigo, 'tentativa de liberar lastro'), 'ainda não usados');

// Janela temporal (art. 15 §4º): nota de 2024 não lastreia meta de 2026.
relogio = new Date('2026-10-02T12:00:00Z');
ok(reg.registrarNFe(coop, { chave: nfAntiga, emitenteId: coop, destinatarioId: recic, material: 'plastico', massaKg: 800, dataEmissao: '2024-05-10' }));
ok(reg.confirmarRecebimento(recic, nfAntiga, { mtr: 'MTR-2024-9', cdf: 'CDF-2024-9', massaRecebidaKg: 800, data: '2024-05-11' }));
ok(reg.homologarNFe(verif, nfAntiga, 'autorizada'));
falha(reg.emitirCertificado(entidade, { empresaId: empresa, material: 'plastico', anoMeta: 2026, massaKg: 300 }), 'Lastro insuficiente');

// Cancelamento devolve o saldo ao lastro.
const c2 = ok(reg.emitirCertificado(entidade, { empresaId: empresa, material: 'plastico', anoMeta: 2026, massaKg: 140 }));
assert.equal(reg.massas()[nfFerro].saldoG, 0);
ok(reg.cancelarCertificado(entidade, c2.codigo, 'Erro de digitação na massa'));
assert.equal(reg.massas()[nfFerro].saldoG, 140000);

// ── Livro-razão: reconstrução e detecção de adulteração ───────────────────
assert.ok(reg.verificarIntegridade().ok);
const copia = JSON.parse(JSON.stringify(reg.eventos));
const refeito = C.Registro.deEventos(copia);
assert.ok(refeito.integridade.ok);
assert.deepEqual(refeito.registro.massas(), reg.massas());
assert.deepEqual(refeito.registro.resumo(), reg.resumo());

const adulterado = JSON.parse(JSON.stringify(reg.eventos));
const alvo = adulterado.find((e) => e.tipo === 'NFE_RECEBIMENTO_CONFIRMADO');
alvo.dados.massaG = 9999999; // inflar a massa recebida
const r = C.verificarCadeia(adulterado);
assert.ok(!r.ok);
assert.equal(r.quebraEm, alvo.seq);
const recusado = C.Registro.deEventos(adulterado);
assert.ok(!recusado.integridade.ok);
assert.equal(recusado.registro.eventos.length, 0, 'cadeia adulterada não é carregada');

const semUm = JSON.parse(JSON.stringify(reg.eventos));
semUm.splice(3, 1);
assert.ok(!C.verificarCadeia(semUm).ok, 'evento removido é detectado');

// ── Data do dia no fuso local ─────────────────────────────────────────────
const noite = new Date('2026-11-08T01:30:00Z'); // 22h30 de 07/11 em São Paulo
assert.equal(C.dataLocalIso(noite), '2026-11-07');
const regNoite = new C.Registro({ agora: () => noite });
const coopN = ok(regNoite.cadastrarParticipante({ tipo: 'cooperativa', nome: 'Coop Noturna', doc: cnpj(70000007), uf: 'SP' })).id;
const recN = ok(regNoite.cadastrarParticipante({ tipo: 'reciclador', nome: 'Recicla Noite', doc: cnpj(80000008), uf: 'SP' })).id;
ok(regNoite.registrarNFe(coopN, { chave: C.gerarChave({ uf: 'SP', ano: 2026, mes: 11, cnpj: regNoite.participante(coopN).doc, numero: 5 }), emitenteId: coopN, destinatarioId: recN, material: 'vidro', massaKg: 50, dataEmissao: '2026-11-07' }));
falha(regNoite.registrarNFe(coopN, { chave: C.gerarChave({ uf: 'SP', ano: 2026, mes: 11, cnpj: regNoite.participante(coopN).doc, numero: 6 }), emitenteId: coopN, destinatarioId: recN, material: 'vidro', massaKg: 50, dataEmissao: '2026-11-08' }), 'futuro');
// Réveillon às 22h: a meta do ano seguinte ainda não pode ser emitida.
const reveillon = new C.Registro({ agora: () => new Date('2027-01-01T01:00:00Z') });
assert.equal(C.dataLocalIso(new Date('2027-01-01T01:00:00Z')), '2026-12-31');
const ent = ok(reveillon.cadastrarParticipante({ tipo: 'entidade', nome: 'Gestora', doc: cnpj(90000009), uf: 'SP' })).id;
const emp = ok(reveillon.cadastrarParticipante({ tipo: 'empresa', nome: 'Empresa', doc: cnpj(91000009), uf: 'SP' })).id;
falha(reveillon.emitirCertificado(ent, { empresaId: emp, material: 'vidro', anoMeta: 2027, massaKg: 1 }), 'entre 2024 e 2026');

console.log('ireverse-core: todos os cenários passaram');
