"""Planilha e painel /vacina-pmo sincronizados sem apertar "Sincronizar".

Em 24/11/2026 a aba do dia foi reordenada e as vacinas marcadas no painel não
chegaram à planilha: o banco guardava os números antigos das linhas, a trava
recusava gravar e só o botão "Sincronizar" (ou o sync agendado, desligado)
realinhava. Estes testes fixam o contrato da sincronização ao vivo e, acima de
tudo, que ela nunca apaga o que a equipe registrou no painel.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from extensions import db
from models import PmoVaccinationAnimal, PmoVaccinationVisit
from services import pmo_realtime, pmo_sheet_live as ao_vivo
from services import vacina_pmo_service as servico

PLANILHA = "plan-ao-vivo"
ABA_GID = "2411"
ABA_TITULO = "24/11/2026"

ANA = ("Ana Souza", "16991110001", "Rua A", "10", "Centro", "Rex")
MARIA = ("Maria Clara", "16991110002", "Rua B", "20", "Centro", "Mel")
BRUNO = ("Bruno Lima", "16991110003", "Rua C", "30", "Centro", "Thor")


def _crua(pessoa, animais=None, caes=None, vacinados=("", "")):
    tutor, telefone, rua, numero, bairro, animal = pessoa
    nomes = animais if animais is not None else animal
    total = caes if caes is not None else len([n for n in nomes.split(",") if n.strip()])
    return [tutor, rua, numero, "", bairro, telefone, "", str(total), "0", nomes, "", "",
            vacinados[0], vacinados[1], "", "", ABA_TITULO, "Manhã"]


class _Aba:
    """Aba em memória: leitura por linha, leitura da aba inteira e gravações."""

    def __init__(self, linhas):
        self.linhas = linhas  # lista; índice 0 = linha 1
        self.gravacoes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, *, spreadsheetId, range, **kwargs):
        from unittest.mock import MagicMock
        faixa = range.split("!", 1)[1]
        if faixa == "A:H":
            valores = [linha[:8] for linha in self.linhas]
        else:
            numero = int(faixa.split(":")[0][1:])
            valores = [self.linhas[numero - 1][:8]] if 0 < numero <= len(self.linhas) else []
        resposta = MagicMock()
        resposta.execute.return_value = {"values": valores}
        return resposta

    def update(self, *, spreadsheetId, range, valueInputOption, body):
        from unittest.mock import MagicMock
        import re
        self.gravacoes.append((range, body["values"]))
        faixa = range.split("!", 1)[1]
        match = re.fullmatch(r"([A-Z])(\d+)(?::([A-Z])\d+)?", faixa)
        if match:
            coluna = ord(match.group(1)) - ord("A")
            linha = self.linhas[int(match.group(2)) - 1]
            for desloc, valor in enumerate(body["values"][0]):
                while len(linha) <= coluna + desloc:
                    linha.append("")
                linha[coluna + desloc] = str(valor)
        return MagicMock()

    def batchUpdate(self, *, spreadsheetId, body):
        from unittest.mock import MagicMock
        return MagicMock()


@pytest.fixture
def aba(app, monkeypatch):
    app.config["PMO_LIVE_SHEET_SYNC"] = True
    app.config["PMO_LIVE_SYNC_INLINE"] = True
    ao_vivo.reset_state()
    monkeypatch.setattr(servico, "_pmo_geocode_address", lambda address: None)
    planilha = _Aba([["Nome completo do tutor", "Endereço"]])
    leituras = []

    def ler(*, sheet_gid="", sheet_title=""):
        leituras.append(sheet_gid)
        return servico.PmoTabValues(
            values=[list(linha) for linha in planilha.linhas],
            spreadsheet_id=PLANILHA, sheet_range="A:T", sheet_gid=ABA_GID, sheet_title=ABA_TITULO,
        )

    monkeypatch.setattr(servico, "read_vacina_pmo_tab", ler)
    monkeypatch.setattr(servico, "list_vacina_pmo_sheets", lambda **kw: [
        {"title": ABA_TITULO, "gid": ABA_GID, "date": "2026-11-24"},
        {"title": "Vacinação 2026", "gid": "0", "date": None},
    ])
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: planilha)
    planilha.leituras = leituras
    yield planilha
    ao_vivo.reset_state()


def _visita(tutor):
    db.session.expire_all()
    return PmoVaccinationVisit.query.filter_by(sheet_gid=ABA_GID, tutor_name=tutor).one()


def _eventos():
    return [e for e in pmo_realtime.get_pmo_events_since(0, ABA_GID)["events"] if e["type"] == "sheet_synced"]


def test_reordenar_a_aba_realinha_o_painel_sozinho(aba):
    aba.linhas += [_crua(ANA), _crua(MARIA), _crua(BRUNO)]
    assert ao_vivo.check_tab_for_changes(ABA_GID) is True
    assert _visita("Maria Clara").source_row == 3

    aba.linhas[1:] = [_crua(BRUNO), _crua(ANA), _crua(MARIA)]
    eventos_antes = len(_eventos())
    assert ao_vivo.check_tab_for_changes(ABA_GID) is True

    assert [_visita(t).source_row for t in ("Bruno Lima", "Ana Souza", "Maria Clara")] == [2, 3, 4]
    assert len(_eventos()) == eventos_antes + 1, "os painéis abertos recarregam"


def test_aba_sem_mudanca_nao_reaplica(aba, monkeypatch):
    aba.linhas += [_crua(ANA)]
    ao_vivo.check_tab_for_changes(ABA_GID)
    chamadas = []
    original = servico.persist_vacina_pmo_rows
    monkeypatch.setattr(servico, "persist_vacina_pmo_rows", lambda *a, **k: chamadas.append(1) or original(*a, **k))

    assert ao_vivo.check_tab_for_changes(ABA_GID) is False
    assert chamadas == []


def test_conferencia_respeita_o_intervalo_por_aba(aba, app):
    aba.linhas += [_crua(ANA)]
    with app.test_request_context():
        assert ao_vivo.maybe_check_tab(ABA_GID) is True
        assert ao_vivo.maybe_check_tab(ABA_GID) is False
    assert aba.leituras == [ABA_GID]


def test_aba_mestre_e_listas_nao_entram(aba, app):
    with app.test_request_context():
        ao_vivo.maybe_check_tab("0")
    assert aba.leituras == []
    assert ao_vivo.sync_tab_now("0") is False


def test_marcar_com_a_aba_editada_regrava_na_linha_certa(aba):
    """Linha redigitada (nome corrigido): a trava recusa e o sync da aba resolve."""
    aba.linhas += [_crua(ANA), _crua(MARIA)]
    ao_vivo.check_tab_for_changes(ABA_GID)
    maria = _visita("Maria Clara")

    # Alguém corrigiu o nome na planilha e inseriu uma casa acima.
    corrigida = ("Maria Clara Souza",) + MARIA[1:]
    aba.linhas[1:] = [_crua(BRUNO), _crua(ANA), _crua(corrigida)]

    servico.update_vacina_pmo_animal_status(maria.animals[0].id, "vacinado")

    visita = db.session.get(PmoVaccinationVisit, maria.id)
    db.session.refresh(visita)
    assert visita.source_row == 4
    assert visita.animals[0].status == "vacinado"
    linha = aba.linhas[3]
    assert "Mel: vacinado" in linha[10]
    assert linha[12:14] == ["1", "0"]
    assert all(not linha[10] for linha in aba.linhas[1:3]), "nada cai na linha dos outros"


def test_nome_completado_na_mesma_linha_mantem_o_registro(aba):
    aba.linhas += [_crua(MARIA)]
    ao_vivo.check_tab_for_changes(ABA_GID)
    maria = _visita("Maria Clara")
    maria.animals[0].status = "vacinado"
    db.session.commit()

    aba.linhas[1] = _crua(("Maria Clara Souza",) + MARIA[1:])
    ao_vivo.check_tab_for_changes(ABA_GID)

    visita = _visita("Maria Clara Souza")
    assert visita.id == maria.id
    assert visita.source_row == 2
    assert visita.animals[0].status == "vacinado"


@pytest.mark.parametrize("outro_nome, outro_telefone", [
    ("Maria Eduarda", MARIA[1]),          # outra pessoa da casa
    ("Maria Clara Souza", "16990000000"),  # nome completado, mas outro telefone
])
def test_outra_pessoa_na_linha_nao_herda_as_vacinas(aba, outro_nome, outro_telefone):
    aba.linhas += [_crua(MARIA)]
    ao_vivo.check_tab_for_changes(ABA_GID)
    maria = _visita("Maria Clara")
    maria.animals[0].status = "vacinado"
    db.session.commit()

    aba.linhas[1] = _crua((outro_nome, outro_telefone) + MARIA[2:])
    ao_vivo.check_tab_for_changes(ABA_GID)

    nova = _visita(outro_nome)
    assert nova.id != maria.id
    # Mesmo animal na mesma casa pode sair "já imunizado" pela dose anterior;
    # vacinado hoje, nunca.
    assert nova.animals[0].status != "vacinado"
    assert db.session.get(PmoVaccinationVisit, maria.id).animals[0].status == "vacinado"


def test_animal_incluido_no_painel_nao_some_antes_de_chegar_a_aba(aba, monkeypatch):
    aba.linhas += [_crua(ANA)]
    ao_vivo.check_tab_for_changes(ABA_GID)
    ana = _visita("Ana Souza")
    ana.synced_at = ana.synced_at - timedelta(minutes=1)  # a equipe mexe minutos depois
    db.session.commit()

    # A gravação da coluna J falha (API fora do ar) logo depois da inclusão.
    monkeypatch.setattr(servico, "write_animal_names_to_sheet", lambda visit: False)
    monkeypatch.setattr(servico, "write_animal_counts_to_sheet", lambda visit: False)
    servico.add_vacina_pmo_visit_animal(ana.id, "Luna", "cao")
    monkeypatch.undo()
    monkeypatch.setattr(servico, "_pmo_geocode_address", lambda address: None)
    monkeypatch.setattr(servico, "_get_sheets_service_rw", lambda: aba)
    monkeypatch.setattr(servico, "read_vacina_pmo_tab", lambda **kw: servico.PmoTabValues(
        values=[list(l) for l in aba.linhas], spreadsheet_id=PLANILHA, sheet_range="A:T",
        sheet_gid=ABA_GID, sheet_title=ABA_TITULO))
    monkeypatch.setattr(servico, "list_vacina_pmo_sheets", lambda **kw: [
        {"title": ABA_TITULO, "gid": ABA_GID, "date": "2026-11-24"}])

    aba.linhas[1][10] = "portão azul"  # outra edição qualquer dispara a leitura
    ao_vivo.check_tab_for_changes(ABA_GID)

    nomes = [a.name for a in _visita("Ana Souza").animals]
    assert nomes == ["Rex", "Luna"]
    assert "Luna" in aba.linhas[1][9], "a aba recebe a versão do painel"


def test_animal_tirado_da_aba_depois_de_sincronizado_sai_do_painel(aba):
    aba.linhas += [_crua(ANA, animais="Rex, Luna")]
    ao_vivo.check_tab_for_changes(ABA_GID)
    assert [a.name for a in _visita("Ana Souza").animals] == ["Rex", "Luna"]

    aba.linhas[1] = _crua(ANA, animais="Rex")
    ao_vivo.check_tab_for_changes(ABA_GID)

    assert [a.name for a in _visita("Ana Souza").animals] == ["Rex"]


def test_contagem_de_vacinados_que_nao_chegou_e_regravada(aba):
    aba.linhas += [_crua(ANA)]
    ao_vivo.check_tab_for_changes(ABA_GID)
    animal = _visita("Ana Souza").animals[0]
    animal.status = "vacinado"
    db.session.commit()

    aba.linhas[1][10] = "obs nova"
    ao_vivo.check_tab_for_changes(ABA_GID)

    assert aba.linhas[1][12:14] == ["1", "0"]


def test_contagem_digitada_a_mao_sem_registro_no_painel_fica(aba):
    aba.linhas += [_crua(ANA, vacinados=("1", "0"))]
    ao_vivo.check_tab_for_changes(ABA_GID)
    assert not [g for g in aba.gravacoes if g[0].endswith("M2:N2")]


def test_pedidos_em_sequencia_viram_um_sync_so(aba, app, monkeypatch):
    app.config["PMO_LIVE_SYNC_INLINE"] = False
    syncs = []
    monkeypatch.setattr(ao_vivo, "sync_tab_now", lambda gid, title="", **kw: syncs.append(gid))
    monkeypatch.setattr(ao_vivo, "debounce_seconds", lambda: 0.2)
    import threading, time
    with app.test_request_context():
        assert ao_vivo.request_tab_sync(ABA_GID, reason="a") is True
        assert ao_vivo.request_tab_sync(ABA_GID, reason="b") is True
        assert ao_vivo.request_tab_sync(ABA_GID, reason="c") is True
    for _ in range(50):
        if not any(t.name.startswith("pmo-live-sync") for t in threading.enumerate()):
            break
        time.sleep(0.05)
    assert syncs == [ABA_GID]


def test_gravacao_feita_durante_o_sync_nao_reagenda(aba, app):
    with ao_vivo.applying(ABA_GID):
        with app.test_request_context():
            assert ao_vivo.request_tab_sync(ABA_GID) is False


def test_desligado_por_variavel_de_ambiente(aba, app, monkeypatch):
    monkeypatch.setenv("PMO_LIVE_SHEET_SYNC", "0")
    with app.test_request_context():
        assert ao_vivo.maybe_check_tab(ABA_GID) is False
        assert ao_vivo.request_tab_sync(ABA_GID) is False


def test_ia_responde_igual_para_a_mesma_celula(monkeypatch):
    servico._PMO_AI_PARSE_CACHE.clear()
    chamadas = []

    def ia(value, dogs, cats):
        chamadas.append(value)
        return [{"name": f"Nome{len(chamadas)}", "species": "cao"}]

    monkeypatch.setattr(servico, "_parse_animals_ai_uncached", ia)
    primeira = servico._parse_animals_ai("Bob e Mel", 1, 0)
    segunda = servico._parse_animals_ai("Bob e Mel", 1, 0)
    assert primeira == segunda
    assert len(chamadas) == 1
    servico._PMO_AI_PARSE_CACHE.clear()
