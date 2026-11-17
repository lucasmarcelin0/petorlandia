"""Marcelino Academy: matérias, matrícula, lições, testes com correção e comentários."""
from flask import g

from extensions import db
from models import User
from models.academy import (AcademyComentario, AcademyLicao, AcademyMateria, AcademyQuestao, AcademyResposta,
                            AcademyTeste, AcademyVinculo)

NEGADO = (403, 404)


def conta(email, role='adotante'):
    user = User(name=email.split('@')[0].title(), email=email, password_hash='x', role=role)
    db.session.add(user)
    db.session.commit()
    return user


def entrar(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    for chave in ('_login_user', '_academy_vinculos', 'user_experience', '_site_flag_cache'):
        g.pop(chave, None)


def _curso(client):
    """Admin cria a matéria, nomeia o professor; professor matricula o aluno e monta uma lição."""
    admin = conta('admin@example.test', role='admin')
    professor = conta('prof@example.test')
    aluno = conta('aluno@example.test')
    entrar(client, admin)
    assert client.post('/academy/materias', data={'nome': 'Inglês básico'}).status_code == 302
    materia = AcademyMateria.query.one()
    client.post(f'/academy/materia/{materia.id}/pessoas', data={'email': 'PROF@example.test', 'papel': 'professor'})

    entrar(client, professor)
    client.post(f'/academy/materia/{materia.id}/pessoas', data={'email': 'aluno@example.test', 'papel': 'aluno'})
    client.post(f'/academy/materia/{materia.id}/licoes', data={'titulo': 'Simple past'})
    licao = AcademyLicao.query.one()
    client.post(f'/academy/licao/{licao.id}/editar', data={
        'titulo': 'Simple past', 'conteudo': 'Use o passado para ações concluídas.', 'ordem': '1',
        'publicada': '1', 'link_video': ''})
    client.post(f'/academy/licao/{licao.id}/testes', data={'nome': 'Exercícios 1'})
    teste = AcademyTeste.query.one()
    client.post(f'/academy/teste/{teste.id}/questoes', data={
        'enunciado': 'Yesterday I ___ to the vet.', 'tipo': 'unica', 'opcoes': '*went\ngoed\ngone'})
    client.post(f'/academy/teste/{teste.id}/questoes', data={
        'enunciado': 'Quais são verbos irregulares?', 'tipo': 'multipla', 'opcoes': '*go\nplay\n*eat'})
    client.post(f'/academy/teste/{teste.id}/questoes', data={
        'enunciado': 'Escreva uma frase no passado.', 'tipo': 'aberta', 'opcoes': ''})
    return dict(admin=admin, professor=professor, aluno=aluno, materia=materia, licao=licao, teste=teste)


def test_fluxo_completo_do_aluno_com_correcao_automatica_e_do_professor(client):
    c = _curso(client)
    unica, multipla, aberta = AcademyQuestao.query.order_by(AcademyQuestao.ordem).all()
    assert [q.tipo for q in (unica, multipla, aberta)] == ['unica', 'multipla', 'aberta']
    assert [o.correta for o in unica.opcoes] == [True, False, False]

    entrar(client, c['aluno'])
    assert client.get('/academy/').status_code == 200
    pagina = client.get(f'/academy/licao/{c["licao"].id}').get_data(as_text=True)
    assert 'Use o passado para ações concluídas.' in pagina and 'Yesterday I ___ to the vet.' in pagina

    certa = unica.opcoes[0].id
    client.post(f'/academy/questao/{unica.id}/responder', data={'opcao': str(certa)})
    go, play, eat = (o.id for o in multipla.opcoes)
    client.post(f'/academy/questao/{multipla.id}/responder', data={'opcao': [str(go), str(play)]})
    client.post(f'/academy/questao/{aberta.id}/responder', data={'texto': 'I adopted a dog.'})
    notas = {r.questao_id: r.nota for r in AcademyResposta.query}
    assert notas == {unica.id: 1, multipla.id: 0, aberta.id: None}

    # Não responde duas vezes.
    client.post(f'/academy/questao/{unica.id}/responder', data={'opcao': str(unica.opcoes[1].id)})
    assert AcademyResposta.query.filter_by(questao_id=unica.id).count() == 1

    resultado = client.get(f'/academy/teste/{c["teste"].id}/resultado').get_data(as_text=True)
    assert '1 certa(s) de 3' in resultado

    # Professor corrige a resposta aberta.
    entrar(client, c['professor'])
    assert 'I adopted a dog.' in client.get('/academy/correcoes').get_data(as_text=True)
    resposta = AcademyResposta.query.filter_by(questao_id=aberta.id).one()
    client.post(f'/academy/resposta/{resposta.id}/corrigir', data={'nota': '1', 'observacao': 'Very good!'})
    assert db.session.get(AcademyResposta, resposta.id).nota == 1
    turma = client.get(f'/academy/materia/{c["materia"].id}').get_data(as_text=True)
    assert 'Aluno' in turma and 'Desempenho da turma' in turma


def test_quem_nao_esta_matriculado_nao_ve_o_curso(client):
    c = _curso(client)
    estranho = conta('estranho@example.test')
    entrar(client, estranho)
    assert client.get('/academy/').status_code in NEGADO
    assert client.get(f'/academy/materia/{c["materia"].id}').status_code in NEGADO
    assert client.get(f'/academy/licao/{c["licao"].id}').status_code in NEGADO
    q = AcademyQuestao.query.first()
    assert client.post(f'/academy/questao/{q.id}/responder', data={'opcao': '1'}).status_code in NEGADO
    assert AcademyResposta.query.count() == 0


def test_aluno_nao_edita_e_professor_nao_nomeia_professor(client):
    c = _curso(client)
    entrar(client, c['aluno'])
    assert client.get(f'/academy/licao/{c["licao"].id}/editar').status_code in NEGADO
    assert client.post(f'/academy/materia/{c["materia"].id}/licoes', data={'titulo': 'X'}).status_code in NEGADO
    assert client.get('/academy/correcoes').status_code in NEGADO

    entrar(client, c['professor'])
    conta('outro@example.test')
    resp = client.post(f'/academy/materia/{c["materia"].id}/pessoas',
                       data={'email': 'outro@example.test', 'papel': 'professor'})
    assert resp.status_code in NEGADO
    assert AcademyVinculo.query.filter_by(papel='professor').count() == 1


def test_rascunho_e_acesso_encerrado_somem_para_o_aluno(client):
    c = _curso(client)
    entrar(client, c['professor'])
    client.post(f'/academy/materia/{c["materia"].id}/licoes', data={'titulo': 'Present perfect'})
    rascunho = AcademyLicao.query.filter_by(titulo='Present perfect').one()
    assert rascunho.publicada is False

    entrar(client, c['aluno'])
    assert 'Present perfect' not in client.get(f'/academy/materia/{c["materia"].id}').get_data(as_text=True)
    assert client.get(f'/academy/licao/{rascunho.id}').status_code == 404

    entrar(client, c['professor'])
    vinculo = AcademyVinculo.query.filter_by(user_id=c['aluno'].id).one()
    client.post(f'/academy/vinculo/{vinculo.id}/revogar')
    assert db.session.get(AcademyVinculo, vinculo.id).revogado_em is not None
    entrar(client, c['aluno'])
    assert client.get(f'/academy/licao/{c["licao"].id}').status_code in NEGADO


def test_validacoes_da_questao_e_comentario(client):
    c = _curso(client)
    entrar(client, c['professor'])
    antes = AcademyQuestao.query.count()
    url = f'/academy/teste/{c["teste"].id}/questoes'
    client.post(url, data={'enunciado': 'Sem correta', 'tipo': 'unica', 'opcoes': 'a\nb'})
    client.post(url, data={'enunciado': 'Duas certas', 'tipo': 'unica', 'opcoes': '*a\n*b'})
    client.post(url, data={'enunciado': 'Uma opção', 'tipo': 'multipla', 'opcoes': '*a'})
    assert AcademyQuestao.query.count() == antes
    assert client.post(f'/academy/licao/{c["licao"].id}/editar', data={
        'titulo': 'Simple past', 'link_video': 'javascript:alert(1)', 'publicada': '1'}).status_code == 302
    assert db.session.get(AcademyLicao, c['licao'].id).link_video is None

    entrar(client, c['aluno'])
    client.post(f'/academy/licao/{c["licao"].id}', data={'comentario': '<script>x</script> dúvida'})
    assert AcademyComentario.query.count() == 1
    pagina = client.get(f'/academy/licao/{c["licao"].id}').get_data(as_text=True)
    assert '&lt;script&gt;x&lt;/script&gt; dúvida' in pagina


def test_area_aparece_no_painel_so_para_quem_tem_acesso(app):
    from flask_login import login_user
    from services.workspaces import resolve_experience
    from services import academy as servico

    aluno = conta('aluno@example.test')
    estranho = conta('estranho@example.test')
    materia = AcademyMateria(nome='Inglês')
    db.session.add(materia)
    db.session.flush()
    db.session.add(AcademyVinculo(materia_id=materia.id, user_id=aluno.id, papel='aluno'))
    db.session.commit()
    with app.test_request_context():
        login_user(aluno)
        assert servico.tem_acesso(aluno)
        assert 'academy' in [w.key for w in resolve_experience(aluno, academy=True).workspaces]
        g.pop('_academy_vinculos', None)
        assert not servico.tem_acesso(estranho)
