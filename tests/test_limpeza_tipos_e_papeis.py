"""Limpeza urbana: tipos e papéis cadastrados pelo admin, "Outro" virando tipo e recorte por tipo."""
import importlib.util
from pathlib import Path

from extensions import db
from models import User
from models.limpeza import LimpezaAcesso, LimpezaEvento, LimpezaPapel, LimpezaSolicitacao, LimpezaTipo
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


def test_filtro_por_tipo_nao_confunde_chave_que_contem_outra(client, uploads):
    _admin(client)
    client.post('/limpeza-urbana/tipos', data={'rotulo': 'Lixo hospitalar'})
    hospitalar = _comunicar_como(client, 'a@example.test', 'lixo-hospitalar')
    comum = _comunicar_como(client, 'b@example.test', 'lixo')
    assert [s.id for s in servico.consultar(categoria='lixo')] == [comum.id]
    assert [s.id for s in servico.consultar(tipos={'lixo-hospitalar'})] == [hospitalar.id]
    assert servico.consultar(tipos=frozenset()) == []


def _papel(client, nome, permissoes, tipos=()):
    dados = {'nome': nome, 'permissao': list(permissoes)}
    if tipos:
        dados['tipo'] = list(tipos)
    else:
        dados['tipos_todos'] = '1'
    return client.post('/limpeza-urbana/papeis', data=dados, follow_redirects=True)


def _atribuir(client, email, *chaves, **extra):
    return client.post('/limpeza-urbana/acessos', data={'emails': email, 'papel': list(chaves), **extra},
                       follow_redirects=True)


def test_admin_cria_papel_com_permissoes_e_tipos_sem_duplicar(client, uploads):
    galhos = _comunicar_como(client, 'a@example.test', 'galhos')
    lixo = _comunicar_como(client, 'b@example.test', 'lixo')
    misto = _comunicar_como(client, 'c@example.test', ['lixo', 'canteiro'])
    _admin(client)
    assert client.get('/limpeza-urbana/acessos').status_code == 200
    assert {p.chave for p in LimpezaPapel.query} == {'colaborador', 'equipe', 'fiscal'}  # papéis iniciais gravados

    _papel(client, 'Equipe de poda', ['comprovar'], ['galhos', 'canteiro'])
    poda = LimpezaPapel.query.filter_by(nome='Equipe de poda').one()
    # Comprovar exige o mapa: a permissão entra sozinha.
    assert (poda.chave, poda.permissoes, poda.tipos) == ('equipe-de-poda', 'mapa,comprovar', 'galhos,canteiro')
    pagina = _papel(client, '  equipe de PODA ', ['comunicar']).get_data(as_text=True)
    assert 'Já existe o papel' in pagina
    assert LimpezaPapel.query.filter(LimpezaPapel.nome.ilike('%poda%')).count() == 1
    assert 'Marque pelo menos uma coisa' in _papel(client, 'Vazio', []).get_data(as_text=True)

    gari = conta('gari@example.test')
    _atribuir(client, gari.email, 'equipe-de-poda')
    entrar(client, gari)
    pontos = {p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']}
    assert pontos == {galhos.id, misto.id}
    assert client.get(f'/limpeza-urbana/solicitacao/{lixo.id}').status_code in NEGADO
    assert comprovar(client, lixo.id).status_code in NEGADO
    assert comprovar(client, galhos.id).status_code == 302
    assert db.session.get(LimpezaSolicitacao, galhos.id).status == 'concluida'
    # Sem "comunicar" no papel, não comunica.
    assert client.get('/limpeza-urbana/comunicar').status_code in NEGADO
    filtro = client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    assert 'value="galhos"' in filtro and 'value="lixo"' not in filtro


def test_fiscalizacao_escolhe_recusar_descartar_e_exportar(client, uploads):
    item = _comunicar_como(client, 'a@example.test', 'entulho')
    outro = _comunicar_como(client, 'b@example.test', 'galhos')
    _admin(client)
    _papel(client, 'Auditor', ['exportar'], ['entulho'])
    _papel(client, 'Triagem', ['descartar'])
    auditor, triagem = conta('auditor@example.test'), conta('triagem@example.test')
    _atribuir(client, auditor.email, 'auditor')
    _atribuir(client, triagem.email, 'triagem')

    entrar(client, auditor)
    linhas = client.get('/limpeza-urbana/relatorio.csv').get_data(as_text=True).strip().splitlines()
    assert len(linhas) == 2 and 'Entulho' in linhas[1]
    assert 'Exportar relatório' in client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    assert client.post(f'/limpeza-urbana/solicitacao/{item.id}/descartar', data={'motivo': 'x'}).status_code in NEGADO
    ficha = client.get(f'/limpeza-urbana/solicitacao/{item.id}').get_data(as_text=True)
    assert 'Descartar esta comunicação' not in ficha

    entrar(client, triagem)
    assert client.get('/limpeza-urbana/relatorio.csv').status_code in NEGADO
    assert 'Exportar relatório' not in client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    assert 'Descartar esta comunicação' in client.get(f'/limpeza-urbana/solicitacao/{outro.id}').get_data(as_text=True)
    client.post(f'/limpeza-urbana/solicitacao/{outro.id}/descartar', data={'motivo': 'Duplicada'})
    assert db.session.get(LimpezaSolicitacao, outro.id).status == 'descartada'


def test_editar_papel_vale_na_hora_e_excluir_revoga_os_acessos(client, uploads):
    lixo = _comunicar_como(client, 'a@example.test', 'lixo')
    _admin(client)
    _papel(client, 'Equipe de poda', ['comprovar'], ['galhos'])
    poda = LimpezaPapel.query.filter_by(chave='equipe-de-poda').one()
    gari = conta('gari@example.test')
    _atribuir(client, gari.email, 'equipe-de-poda')

    entrar(client, gari)
    assert client.get('/limpeza-urbana/mapa/dados').get_json()['pontos'] == []
    entrar(client, User.query.filter_by(email='admin@example.test').one())
    client.post(f'/limpeza-urbana/papeis/{poda.id}', data={'nome': 'Equipe de poda e lixo',
                                                          'permissao': ['comprovar'], 'tipo': ['galhos', 'lixo']})
    assert db.session.get(LimpezaPapel, poda.id).nome == 'Equipe de poda e lixo'
    entrar(client, gari)
    assert [p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']] == [lixo.id]

    entrar(client, User.query.filter_by(email='admin@example.test').one())
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    assert '1 pessoa com este papel' in pagina and 'perde esse acesso' in pagina
    client.post(f'/limpeza-urbana/papeis/{poda.id}/excluir')
    assert db.session.get(LimpezaPapel, poda.id).ativo is False
    assert LimpezaAcesso.query.filter_by(user_id=gari.id, revogado_em=None).count() == 0
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    lista = pagina[pagina.index('class="limpeza-papeis"'):pagina.index('Em branco: vale desde hoje')]
    assert 'Equipe de poda e lixo' not in lista
    # O nome fica livre de novo.
    _papel(client, 'Equipe de poda e lixo', ['comunicar'])
    assert LimpezaPapel.query.filter_by(nome='Equipe de poda e lixo', ativo=True).count() == 1
    entrar(client, gari)
    assert client.get('/limpeza-urbana/mapa').status_code in NEGADO


def test_papeis_iniciais_editaveis_sem_mudar_os_acessos(client):
    _admin(client)
    client.get('/limpeza-urbana/acessos')
    fiscal = LimpezaPapel.query.filter_by(chave='fiscal').one()
    pessoa = conta('fiscal@example.test')
    _atribuir(client, pessoa.email, 'fiscal')
    client.post(f'/limpeza-urbana/papeis/{fiscal.id}', data={'nome': 'Fiscalização', 'permissao': ['recusar'],
                                                            'tipos_todos': '1'})
    limpar_g()
    assert servico.permissoes_de(db.session.get(User, pessoa.id)) == {'mapa', 'recusar'}
    assert LimpezaAcesso.query.filter_by(user_id=pessoa.id, papel='fiscal', revogado_em=None).count() == 1


def test_varios_emails_de_uma_vez(client):
    _admin(client)
    um, dois = conta('um@example.test'), conta('dois@example.test')
    texto = _atribuir(client, 'um@example.test, DOIS@example.test\nsemconta@example.test;um@example.test',
                      'equipe').get_data(as_text=True)
    assert '2 contas' in texto and 'semconta@example.test' in texto
    for pessoa in (um, dois):
        assert LimpezaAcesso.query.filter_by(user_id=pessoa.id, papel='equipe', revogado_em=None).count() == 1
    antes = LimpezaAcesso.query.count()
    _atribuir(client, 'x@example.test y@example.test', 'equipe')
    assert LimpezaAcesso.query.count() == antes


def test_editar_prazo_do_acesso_guarda_historico(client):
    _admin(client)
    pessoa = conta('gari@example.test')
    _atribuir(client, pessoa.email, 'equipe')
    antigo = LimpezaAcesso.query.filter_by(user_id=pessoa.id).one()
    client.post(f'/limpeza-urbana/acessos/{antigo.id}/alterar', data={'inicio': '2026-11-01', 'fim': '2026-11-30'})
    novo = LimpezaAcesso.query.filter_by(user_id=pessoa.id, revogado_em=None).one()
    assert novo.id != antigo.id and (novo.papel, str(novo.inicio), str(novo.fim)) == ('equipe', '2026-11-01', '2026-11-30')
    assert LimpezaEvento.query.filter_by(tipo='acesso_alterado').count() == 1
    client.post(f'/limpeza-urbana/acessos/{novo.id}/alterar', data={'inicio': '2026-12-10', 'fim': '2026-12-01'})
    assert db.session.get(LimpezaAcesso, novo.id).revogado_em is None


def test_rotas_de_administracao_sao_so_do_admin(client):
    pessoa = conta('fiscal@example.test')
    dar(pessoa, 'fiscal')
    entrar(client, pessoa)
    for rota in ('/limpeza-urbana/tipos', '/limpeza-urbana/tipos/1', '/limpeza-urbana/tipos/outro',
                 '/limpeza-urbana/papeis', '/limpeza-urbana/papeis/1', '/limpeza-urbana/papeis/1/excluir',
                 '/limpeza-urbana/acessos/1/alterar'):
        assert client.post(rota, data={'rotulo': 'X', 'nome': 'X', 'permissao': 'mapa', 'texto': 'x',
                                       'destino': 'lixo'}).status_code in NEGADO, rota
    assert LimpezaTipo.query.count() == 0 and LimpezaPapel.query.count() == 0


def test_lista_paginada_de_10_em_10_e_mapa_com_todos(client, uploads):
    for _ in range(12):
        _comunicar_como(client, 'a@example.test', 'lixo')
    _admin(client)
    tudo = client.get('/limpeza-urbana/mapa/dados').get_json()
    assert len(tudo['pontos']) == 12 and tudo['total'] == 12 and 'pagina' not in tudo
    primeira = client.get('/limpeza-urbana/mapa/dados?pagina=1').get_json()
    assert (len(primeira['pontos']), primeira['pagina'], primeira['paginas'], primeira['total']) == (10, 1, 2, 12)
    assert primeira['indicadores']['abertas'] == 12  # os números contam o filtro inteiro
    segunda = client.get('/limpeza-urbana/mapa/dados?pagina=2').get_json()
    assert len(segunda['pontos']) == 2
    assert {p['id'] for p in primeira['pontos']}.isdisjoint({p['id'] for p in segunda['pontos']})
    # As mais recentes vêm primeiro; página fora do intervalo cai na última.
    assert primeira['pontos'][0]['id'] > segunda['pontos'][-1]['id']
    assert client.get('/limpeza-urbana/mapa/dados?pagina=99').get_json()['pagina'] == 2
    pagina = client.get('/limpeza-urbana/comunicacoes').get_data(as_text=True)
    assert 'id="limpeza-paginacao"' in pagina and 'Mais antigas' in pagina


def test_numero_da_comunicacao_nao_pula_quando_o_id_pula(client, uploads):
    primeira = _comunicar_como(client, 'a@example.test', 'lixo')
    segunda = _comunicar_como(client, 'a@example.test', 'galhos')
    assert (primeira.numero, segunda.numero) == (1, 2)
    # Simula o id gasto por gravações desfeitas: o próximo id salta, o número não.
    db.session.add(LimpezaSolicitacao(id=40, numero=3, autor_id=primeira.autor_id, categorias='lixo',
                                      latitude=-20.72, longitude=-47.87, origem_local='aparelho',
                                      foto_url='https://x.test/f.jpg', status='aberta'))
    db.session.commit()
    # Comunicação recusada (sem localização) não gasta número.
    assert comunicar(client, categoria='lixo', lat=None).status_code == 400
    quarta = _comunicar_como(client, 'a@example.test', 'entulho')
    assert quarta.id == 41 and quarta.numero == 4
    assert 'Nº 4 ·' in client.get(f'/limpeza-urbana/solicitacao/{quarta.id}').get_data(as_text=True)
    assert 'Nº 4 ·' in client.get('/limpeza-urbana/minhas').get_data(as_text=True)
    _admin(client)
    pontos = client.get('/limpeza-urbana/mapa/dados?pagina=1').get_json()['pontos']
    assert [(p['id'], p['numero']) for p in pontos][:2] == [(41, 4), (40, 3)]
    linhas = client.get('/limpeza-urbana/relatorio.csv').get_data(as_text=True).strip().splitlines()
    assert linhas[1].lstrip('\ufeff').startswith('4;')


def test_admin_ve_como_cada_papel_sem_gravar_nada(client, uploads):
    galhos = _comunicar_como(client, 'a@example.test', 'galhos')
    lixo = _comunicar_como(client, 'b@example.test', 'lixo')
    _admin(client)
    _papel(client, 'Equipe de poda', ['comprovar'], ['galhos'])
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    assert 'Ver como Equipe de poda' in pagina and 'Ver como Colaborador' in pagina

    resposta = client.post('/limpeza-urbana/papeis/equipe-de-poda/ver-como')
    assert resposta.headers['Location'].endswith('/limpeza-urbana/mapa')
    mapa = client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    assert 'Você está vendo como' in mapa and 'Equipe de poda' in mapa
    nav = mapa[mapa.index('limpeza-nav'):mapa.index('</nav>', mapa.index('limpeza-nav'))]
    assert 'Quem acessa' not in nav and 'Todas as comunicações' not in nav and 'Comunicar' not in nav
    assert [p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']] == [galhos.id]
    assert client.get(f'/limpeza-urbana/solicitacao/{lixo.id}').status_code in NEGADO
    assert client.get('/limpeza-urbana/relatorio.csv').status_code in NEGADO
    ficha = client.get(f'/limpeza-urbana/solicitacao/{galhos.id}').get_data(as_text=True)
    assert 'Comprovar atendimento' in ficha and 'disabled' in ficha
    # Nada é gravado em nome do papel simulado.
    assert comprovar(client, galhos.id).status_code == 302
    assert db.session.get(LimpezaSolicitacao, galhos.id).status == 'aberta'
    assert client.post('/limpeza-urbana/papeis', data={'nome': 'X', 'permissao': 'comunicar'}).status_code == 302
    assert LimpezaPapel.query.filter_by(nome='X').count() == 0

    client.post('/limpeza-urbana/ver-como/sair')
    assert len(client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']) == 2
    # Abrir "Quem acessa" também encerra o modo.
    client.post('/limpeza-urbana/papeis/colaborador/ver-como')
    assert client.get('/limpeza-urbana/mapa').status_code in NEGADO
    client.get('/limpeza-urbana/acessos')
    assert client.get('/limpeza-urbana/mapa').status_code == 200

    # Quem não é administrador não entra no modo.
    gari = conta('gari@example.test')
    dar(gari, 'equipe')
    entrar(client, gari)
    assert client.post('/limpeza-urbana/papeis/fiscal/ver-como').status_code in NEGADO
    with client.session_transaction() as s:
        s[servico.SESSAO_VER_COMO] = 'fiscal'
    assert client.get('/limpeza-urbana/relatorio.csv').status_code in NEGADO


def test_mapa_so_com_as_proprias_comunicacoes(client, uploads):
    alheia = _comunicar_como(client, 'vizinho@example.test', 'lixo')
    morador = conta('morador@example.test')
    _admin(client)
    client.get('/limpeza-urbana/acessos')
    _papel(client, 'Morador com mapa', ['comunicar', 'proprias'])
    papel = LimpezaPapel.query.filter_by(nome='Morador com mapa').one()
    # "Só as próprias" exige o mapa: a permissão entra sozinha.
    assert papel.permissoes == 'comunicar,mapa,proprias'
    pagina = client.get('/limpeza-urbana/acessos').get_data(as_text=True)
    assert 'Só as próprias comunicações' in pagina and 'todos os tipos (só as próprias)' in pagina
    _atribuir(client, morador.email, papel.chave)

    entrar(client, morador)
    assert comunicar(client, categoria='galhos').status_code == 302
    minha = LimpezaSolicitacao.query.order_by(LimpezaSolicitacao.id.desc()).first()
    assert 'Mostrando só as comunicações que você fez' in client.get('/limpeza-urbana/mapa').get_data(as_text=True)
    pontos = {p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']}
    assert pontos == {minha.id}
    assert client.get(f'/limpeza-urbana/solicitacao/{alheia.id}').status_code in NEGADO

    # Um outro papel com o mapa completo vale mais que o recorte.
    entrar(client, User.query.filter_by(email='admin@example.test').one())
    _atribuir(client, morador.email, 'equipe')
    entrar(client, morador)
    limpar_g()
    pontos = {p['id'] for p in client.get('/limpeza-urbana/mapa/dados').get_json()['pontos']}
    assert pontos == {minha.id, alheia.id}

    # O admin vendo como o papel também vê só as próprias (nenhuma).
    entrar(client, User.query.filter_by(email='admin@example.test').one())
    client.post(f'/limpeza-urbana/papeis/{papel.chave}/ver-como')
    assert client.get('/limpeza-urbana/mapa/dados').get_json()['pontos'] == []
