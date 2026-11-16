"""Limpeza urbana: tipos cadastrados pelo admin, "Outro" virando tipo, recorte por tipo e perfis."""
import importlib.util
from pathlib import Path

from extensions import db
from models import User
from models.limpeza import LimpezaAcesso, LimpezaEvento, LimpezaPerfil, LimpezaSolicitacao, LimpezaTipo
from services import limpeza_urbana as servico

_spec = importlib.util.spec_from_file_location(
    "_limpeza_base", Path(__file__).resolve().parent / "test_limpeza_urbana.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
conta, entrar, dar, limpar_g, comunicar, comprovar = (base.conta, base.entrar, base.dar, base.limpar_g,
                                                      base.comunicar, base.comprovar)
uploads, NEGADO = base.uploads, base.NEGADO


def _admin(client):
    admin = conta('admin@example.test', role='admin')
    entrar(client, admin)
    return admin


def _comunicar_como(client, email, categoria, **extra):
    pessoa = User.query.filter_by(email=email).first() or conta(email)
    dar(pessoa, 'colaborador')
    entrar(client, pessoa)
    assert comunicar(client, categoria=categoria, **extra).status_code == 302
    return LimpezaSolicitacao.query.order_by(LimpezaSolicitacao.id.desc()).first()


def test_admin_cria_tipo_que_aparece_na_tela_de_comunicar(client, uploads):
    _admin(client)
    assert client.get('/limpeza-urbana/acessos').status_code == 200
    assert LimpezaTipo.query.count() == len(servico.CATEGORIAS)  # conjunto inicial gravado

    client.post('/limpeza-urbana/tipos', data={'rotulo': 'pneus velhos'})
    novo = LimpezaTipo.query.filter_by(rotulo='Pneus velhos').one()
    assert novo.chave == 'pneus-velhos' and novo.ativo
    # Novo tipo entra antes de "Outro", que fica sempre por último.
    limpar_g()
    assert list(servico.catalogo())[-2:] == ['pneus-velhos', 'outro']
    # Nome repetido (sem acento ou maiúscula) não duplica.
    client.post('/limpeza-urbana/tipos', data={'rotulo': 'PNEUS  VELHOS'})
    assert LimpezaTipo.query.filter(LimpezaTipo.rotulo.ilike('pneus%')).count() == 1

    limpar_g()
    pagina = client.get('/limpeza-urbana/comunicar').get_data(as_text=True)
    assert 'value="pneus-velhos"' in pagina and 'Pneus velhos' in pagina

    item = _comunicar_como(client, 'morador@example.test', 'pneus-velhos')
    assert item.categorias == 'pneus-velhos'


def test_tipo_desativado_some_da_tela_mas_nomeia_o_historico(client, uploads):
    item = _comunicar_como(client, 'morador@example.test', 'entulho')
    _admin(client)
    client.get('/limpeza-urbana/acessos')
    entulho = LimpezaTipo.query.filter_by(chave='entulho').one()
    client.post(f'/limpeza-urbana/tipos/{entulho.id}', data={'rotulo': 'Entulho de obra'})
    client.post(f'/limpeza-urbana/tipos/{entulho.id}', data={'ativo': '0'})
    limpar_g()
    assert 'entulho' not in servico.catalogo()
    assert 'value="entulho"' not in client.get('/limpeza-urbana/comunicar').get_data(as_text=True)
    assert 'Entulho de obra' in client.get(f'/limpeza-urbana/solicitacao/{item.id}').get_data(as_text=True)
    # Quem tenta comunicar o tipo desativado (página antiga em cache) é avisado.
    entrar(client, User.query.filter_by(email='morador@example.test').one())
    assert comunicar(client, categoria='entulho').status_code == 400

    outro = LimpezaTipo.query.filter_by(chave='outro').one()
    entrar(client, User.query.filter_by(email='admin@example.test').one())
    client.post(f'/limpeza-urbana/tipos/{outro.id}', data={'ativo': '0'})
    assert db.session.get(LimpezaTipo, outro.id).ativo is True
    assert {'tipo_renomeado', 'tipo_desativado'} <= {e.tipo for e in LimpezaEvento.query}


def test_outro_agrupa_sugestoes_e_vira_tipo(client, uploads):
    a = _comunicar_como(client, 'a@example.test', 'outro', descricao='Pneus velhos')
    b = _comunicar_como(client, 'b@example.test', ['lixo', 'outro'], descricao='  pneus   VELHOS! ')
    c = _comunicar_como(client, 'c@example.test', 'outro', descricao='Animal morto')
    _admin(client)
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    assert 'O que chegou em' in pagina and 'Pneus velhos' in pagina
    sugestoes = servico.sugestoes_outro()
    assert [(s['texto'], s['total']) for s in sugestoes] == [('pneus velhos', 2), ('animal morto', 1)]

    client.post('/limpeza-urbana/tipos/outro', data={'texto': 'pneus velhos', 'destino': 'novo',
                                                     'rotulo': 'Pneus'})
    assert db.session.get(LimpezaSolicitacao, a.id).categorias == 'pneus'
    assert db.session.get(LimpezaSolicitacao, b.id).categorias == 'lixo,pneus'
    assert db.session.get(LimpezaSolicitacao, b.id).descricao.strip() == 'pneus   VELHOS!'  # o texto fica
    assert db.session.get(LimpezaSolicitacao, c.id).categorias == 'outro'
    # Também dá para levar para um tipo que já existe.
    client.post('/limpeza-urbana/tipos/outro', data={'texto': 'animal morto', 'destino': 'lixo'})
    assert db.session.get(LimpezaSolicitacao, c.id).categorias == 'lixo'
    assert servico.sugestoes_outro() == []
    assert LimpezaEvento.query.filter_by(tipo='reclassificada').count() == 3


def test_equipe_restrita_a_alguns_tipos(client, uploads):
    galhos = _comunicar_como(client, 'a@example.test', 'galhos')
    lixo = _comunicar_como(client, 'b@example.test', 'lixo')
    misto = _comunicar_como(client, 'c@example.test', ['lixo', 'canteiro'])
    poda = conta('poda@example.test')
    servico.conceder(poda, ['equipe'], None, None, 'Coordenação', tipos=['galhos', 'canteiro'])
    db.session.commit()
    entrar(client, poda)
    pontos = {p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']}
    assert pontos == {galhos.id, misto.id}
    assert client.get(f'/limpeza-urbana/solicitacao/{lixo.id}').status_code in NEGADO
    assert comprovar(client, lixo.id).status_code in NEGADO
    assert db.session.get(LimpezaSolicitacao, lixo.id).status == 'aberta'
    filtro = client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    assert 'value="galhos"' in filtro and 'value="lixo"' not in filtro
    assert comprovar(client, galhos.id).status_code == 302
    assert db.session.get(LimpezaSolicitacao, galhos.id).status == 'concluida'

    # Um segundo acesso sem recorte (fiscalização de tudo) libera todos os tipos.
    servico.conceder(poda, ['fiscal'], None, None, 'Coordenação')
    db.session.commit()
    limpar_g()
    pontos = {p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']}
    assert pontos == {galhos.id, lixo.id, misto.id}


def test_relatorio_do_fiscal_respeita_o_recorte(client, uploads):
    _comunicar_como(client, 'a@example.test', 'galhos')
    _comunicar_como(client, 'b@example.test', 'entulho')
    fiscal = conta('fiscal@example.test')
    servico.conceder(fiscal, ['fiscal'], None, None, 'Coordenação', tipos=['entulho'])
    db.session.commit()
    entrar(client, fiscal)
    linhas = client.get('/limpeza-urbana/relatorio.csv').get_data(as_text=True).strip().splitlines()
    assert len(linhas) == 2 and 'Entulho' in linhas[1]


def test_filtro_por_tipo_nao_confunde_chave_que_contem_outra(client, uploads):
    _admin(client)
    client.post('/limpeza-urbana/tipos', data={'rotulo': 'Lixo hospitalar'})
    hospitalar = _comunicar_como(client, 'a@example.test', 'lixo-hospitalar')
    comum = _comunicar_como(client, 'b@example.test', 'lixo')
    assert [s.id for s in servico.consultar(categoria='lixo')] == [comum.id]
    assert [s.id for s in servico.consultar(tipos={'lixo-hospitalar'})] == [hospitalar.id]
    assert servico.consultar(tipos=frozenset()) == []


def test_varios_emails_perfil_salvo_e_atalho_de_tipos(client):
    _admin(client)
    um, dois = conta('um@example.test'), conta('dois@example.test')
    resposta = client.post('/limpeza-urbana/acessos', data={
        'emails': 'um@example.test, DOIS@example.test\nsemconta@example.test;um@example.test',
        'papel': ['equipe'], 'tipo': ['galhos', 'canteiro'],
        'salvar_perfil': '1', 'novo_perfil': 'Equipe de poda'}, follow_redirects=True)
    texto = resposta.get_data(as_text=True)
    assert '2 contas' in texto and 'semconta@example.test' in texto
    for pessoa in (um, dois):
        acesso = LimpezaAcesso.query.filter_by(user_id=pessoa.id, revogado_em=None).one()
        assert (acesso.papel, acesso.tipos, acesso.perfil) == ('equipe', 'galhos,canteiro', 'Equipe de poda')
    perfil = LimpezaPerfil.query.one()
    assert (perfil.nome, perfil.papeis, perfil.tipos) == ('Equipe de poda', 'equipe', 'galhos,canteiro')
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    assert 'data-nome="Equipe de poda"' in pagina and 'Galhos e poda, canteiro' in pagina

    # "Todos os tipos" marcado vence os tipos avulsos.
    client.post('/limpeza-urbana/acessos', data={'emails': 'um@example.test', 'papel': 'fiscal',
                                                 'tipos_todos': '1', 'tipo': 'lixo'})
    assert LimpezaAcesso.query.filter_by(user_id=um.id, papel='fiscal').one().tipos is None

    client.post(f'/limpeza-urbana/perfis/{perfil.id}/remover')
    assert db.session.get(LimpezaPerfil, perfil.id).ativo is False
    assert LimpezaAcesso.query.filter_by(user_id=dois.id, revogado_em=None).count() == 1

    # Nenhum e-mail com conta: nada é concedido.
    antes = LimpezaAcesso.query.count()
    client.post('/limpeza-urbana/acessos', data={'emails': 'x@example.test y@example.test', 'papel': 'equipe'})
    assert LimpezaAcesso.query.count() == antes


def test_editar_acesso_troca_tipos_e_prazo_e_guarda_historico(client):
    _admin(client)
    pessoa = conta('gari@example.test')
    client.post('/limpeza-urbana/acessos', data={'emails': pessoa.email, 'papel': 'equipe'})
    antigo = LimpezaAcesso.query.filter_by(user_id=pessoa.id).one()
    client.post(f'/limpeza-urbana/acessos/{antigo.id}/alterar',
                data={'tipo': ['entulho'], 'inicio': '2026-11-01', 'fim': '2026-11-30'})
    vigentes = LimpezaAcesso.query.filter_by(user_id=pessoa.id, revogado_em=None).all()
    assert len(vigentes) == 1 and vigentes[0].id != antigo.id
    novo = vigentes[0]
    assert (novo.papel, novo.tipos, str(novo.inicio), str(novo.fim)) == ('equipe', 'entulho', '2026-11-01', '2026-11-30')
    assert db.session.get(LimpezaAcesso, antigo.id).revogado_em is not None
    assert LimpezaEvento.query.filter_by(tipo='acesso_alterado').count() == 1
    # Data final antes da inicial é recusada sem mexer no acesso.
    client.post(f'/limpeza-urbana/acessos/{novo.id}/alterar', data={'inicio': '2026-12-10', 'fim': '2026-12-01'})
    assert db.session.get(LimpezaAcesso, novo.id).revogado_em is None


def test_rotas_de_administracao_sao_so_do_admin(client):
    pessoa = conta('fiscal@example.test')
    dar(pessoa, 'fiscal')
    entrar(client, pessoa)
    for rota in ('/limpeza-urbana/tipos', '/limpeza-urbana/tipos/1', '/limpeza-urbana/tipos/outro',
                 '/limpeza-urbana/perfis/1/remover', '/limpeza-urbana/acessos/1/alterar'):
        assert client.post(rota, data={'rotulo': 'X', 'texto': 'x', 'destino': 'lixo'}).status_code in NEGADO, rota
    assert LimpezaTipo.query.count() == 0
