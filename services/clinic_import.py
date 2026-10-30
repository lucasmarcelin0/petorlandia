"""Importação de clientes (tutores) e pacientes (animais) por planilha CSV.

Clínica nova chega com a lista de clientes numa planilha; digitar um por um é
o que faz o teste parar no primeiro dia. O fluxo tem duas etapas: ``planejar``
lê a planilha e diz, linha a linha, o que vai acontecer (sem gravar nada);
``aplicar`` refaz o mesmo plano e grava tudo numa transação só.

Mesmas regras do cadastro manual de tutor: e-mail e CPF não podem pertencer a
outra conta fora da clínica; sem e-mail, a conta recebe um e-mail provisório.
Tutor que já é da clínica (mesmo CPF, e-mail ou celular) é reaproveitado, e
animal com o mesmo nome para o mesmo tutor não é cadastrado de novo.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

MAX_LINHAS = 2000
MAX_BYTES = 2 * 1024 * 1024

#: Coluna canônica -> nomes aceitos no cabeçalho (comparados sem acento/caixa).
COLUNAS = {
    'tutor_nome': ('tutor_nome', 'tutor', 'nome do tutor', 'nome_tutor', 'cliente', 'nome do cliente', 'responsavel', 'proprietario'),
    'tutor_celular': ('tutor_celular', 'celular', 'telefone', 'whatsapp', 'fone', 'telefone do tutor'),
    'tutor_email': ('tutor_email', 'email', 'e-mail', 'e_mail'),
    'tutor_cpf': ('tutor_cpf', 'cpf'),
    'animal_nome': ('animal_nome', 'animal', 'pet', 'paciente', 'nome do animal', 'nome_animal', 'nome do pet'),
    'especie': ('especie',),
    'raca': ('raca',),
    'sexo': ('sexo',),
    'nascimento': ('nascimento', 'data de nascimento', 'data_nascimento', 'data nascimento'),
    'peso': ('peso', 'peso (kg)', 'peso_kg'),
    'castrado': ('castrado', 'castrada', 'castracao'),
    'microchip': ('microchip', 'chip'),
}

MODELO_CABECALHO = [
    'tutor_nome', 'tutor_celular', 'tutor_email', 'tutor_cpf',
    'animal_nome', 'especie', 'raca', 'sexo', 'nascimento', 'peso', 'castrado', 'microchip',
]
MODELO_EXEMPLOS = [
    ['Maria Souza', '(16) 99123-4567', 'maria@exemplo.com', '', 'Thor', 'Cachorro', 'Labrador', 'Macho', '15/03/2020', '28,5', 'sim', ''],
    ['Maria Souza', '(16) 99123-4567', 'maria@exemplo.com', '', 'Mia', 'Gato', '', 'Fêmea', '2022-01-10', '4', 'não', ''],
    ['João Lima', '(16) 98888-1111', '', '', '', '', '', '', '', '', '', ''],
]

_ESPECIE_ALIASES = {
    'cao': 'cachorro', 'caes': 'cachorro', 'cachorra': 'cachorro', 'canino': 'cachorro',
    'canina': 'cachorro', 'dog': 'cachorro', 'gata': 'gato', 'felino': 'gato', 'felina': 'gato', 'cat': 'gato',
}


def _chave(texto) -> str:
    """Minúsculas, sem acento e com espaços simples: compara o que a pessoa digitou."""
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', texto).strip().lower()


def _digitos(texto) -> str:
    return re.sub(r'\D', '', str(texto or ''))


def gerar_modelo_csv() -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=';')
    escritor.writerow(MODELO_CABECALHO)
    escritor.writerows(MODELO_EXEMPLOS)
    return saida.getvalue()


class PlanilhaInvalida(ValueError):
    """Arquivo que não dá para ler como planilha de clientes."""


def ler_planilha(conteudo: bytes) -> list[dict]:
    """Lê o CSV (vírgula ou ponto e vírgula; UTF-8 ou Latin-1) em linhas canônicas."""
    if not conteudo or not conteudo.strip():
        raise PlanilhaInvalida('O arquivo está vazio.')
    if len(conteudo) > MAX_BYTES:
        raise PlanilhaInvalida('Arquivo grande demais (máximo de 2 MB). Divida a planilha em partes.')
    if conteudo[:4] == b'PK\x03\x04':
        raise PlanilhaInvalida(
            'Este arquivo é do Excel (.xlsx). No Excel, use Arquivo > Salvar como > '
            '"CSV (separado por vírgulas)" e envie o arquivo .csv.'
        )
    for codificacao in ('utf-8-sig', 'cp1252'):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    primeira = texto.splitlines()[0] if texto.splitlines() else ''
    delimitador = ';' if primeira.count(';') >= primeira.count(',') else ','
    leitor = csv.reader(io.StringIO(texto), delimiter=delimitador)
    cabecalho = next(leitor, None) or []

    mapa = {}
    for indice, nome in enumerate(cabecalho):
        nome_chave = _chave(nome).replace('_', ' ')
        for canonica, aceitos in COLUNAS.items():
            if canonica not in mapa and nome_chave in {_chave(a).replace('_', ' ') for a in aceitos}:
                mapa[canonica] = indice
                break
    if 'tutor_nome' not in mapa:
        raise PlanilhaInvalida(
            'Não achamos a coluna com o nome do tutor. A primeira linha precisa ter os títulos '
            'das colunas, como no modelo (ex.: tutor_nome, tutor_celular, animal_nome).'
        )

    linhas = []
    for valores in leitor:
        if not any((v or '').strip() for v in valores):
            continue
        linha = {
            canonica: (valores[indice].strip() if indice < len(valores) else '')
            for canonica, indice in mapa.items()
        }
        linhas.append(linha)
        if len(linhas) > MAX_LINHAS:
            raise PlanilhaInvalida(f'A planilha passa de {MAX_LINHAS} linhas. Divida em partes menores.')
    if not linhas:
        raise PlanilhaInvalida('A planilha não tem linhas preenchidas abaixo do cabeçalho.')
    return linhas


def _data(texto):
    texto = (texto or '').strip()
    if not texto:
        return None
    for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            valor = datetime.strptime(texto, formato).date()
        except ValueError:
            continue
        if valor > date.today() or valor.year < 1980:
            raise ValueError('data de nascimento fora do esperado')
        return valor
    raise ValueError('data de nascimento inválida (use dd/mm/aaaa)')


def _peso(texto):
    texto = (texto or '').strip().lower().replace('kg', '').strip()
    if not texto:
        return None
    try:
        valor = float(texto.replace(',', '.'))
    except ValueError:
        raise ValueError('peso inválido (use números, como 12,5)') from None
    if not 0 < valor < 1000:
        raise ValueError('peso fora do esperado')
    return valor


def _sexo(texto):
    chave = _chave(texto)
    if not chave:
        return None
    if chave in {'m', 'macho', 'masculino'}:
        return 'Macho'
    if chave in {'f', 'femea', 'feminino'}:
        return 'Fêmea'
    raise ValueError('sexo inválido (use Macho ou Fêmea)')


def _sim_nao(texto):
    chave = _chave(texto)
    if not chave:
        return None
    if chave in {'s', 'sim', 'yes', 'x', '1', 'castrado', 'castrada'}:
        return True
    if chave in {'n', 'nao', 'no', '0'}:
        return False
    raise ValueError('castrado inválido (use sim ou não)')


@dataclass
class LinhaPlanejada:
    numero: int
    tutor_nome: str
    animal_nome: str
    tutor_acao: str = ''          # 'novo', 'existente', 'repetido' (já criado numa linha anterior)
    animal_acao: str = ''         # 'novo', 'existente', '' (linha sem animal)
    erros: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    dados: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.erros


def planejar(linhas: list[dict], clinica_id: int) -> list[LinhaPlanejada]:
    """Diz o que cada linha fará, sem gravar nada."""
    from sqlalchemy import func, or_

    from document_utils import normalize_cpf
    from models import Animal, Breed, Species, User
    from template_filters import normalize_email, normalize_phone

    especies = {_chave(sp.name): sp for sp in Species.query.all()}
    racas = {}
    for raca in Breed.query.all():
        racas.setdefault((raca.species_id, _chave(raca.name)), raca)

    emails = {normalize_email(l.get('tutor_email')) for l in linhas if l.get('tutor_email')}
    emails.discard(None)
    cpfs = {_digitos(l.get('tutor_cpf')) for l in linhas if _digitos(l.get('tutor_cpf'))}

    contas_por_email = {}
    if emails:
        for user in User.query.filter(func.lower(User.email).in_(emails)).all():
            contas_por_email[user.email.lower()] = user
    contas_por_cpf = {}
    if cpfs:
        coluna = User.cpf
        for char in ('.', '-', '/', ' '):
            coluna = func.replace(coluna, char, '')
        for user in User.query.filter(coluna.in_(cpfs)).all():
            contas_por_cpf[_digitos(user.cpf)] = user
    # Só tutores: um celular igual ao de alguém da equipe não pode levar o
    # animal para a conta do funcionário.
    tutores_da_clinica_por_celular = {}
    for user in User.query.filter(
        User.clinica_id == clinica_id,
        User.phone.isnot(None),
        or_(User.worker.is_(None), User.worker == ''),
    ).all():
        tutores_da_clinica_por_celular.setdefault(normalize_phone(user.phone), user)

    nomes_de_animais = {}

    def _animais_existentes(user_id):
        if user_id not in nomes_de_animais:
            nomes_de_animais[user_id] = {
                _chave(nome)
                for (nome,) in Animal.query.with_entities(Animal.name)
                .filter(Animal.user_id == user_id, Animal.removido_em.is_(None))
                .all()
            }
        return nomes_de_animais[user_id]

    vistos_no_arquivo = {}   # chave do tutor -> número da linha que o criou
    animais_no_arquivo = set()
    plano = []
    for numero, linha in enumerate(linhas, start=2):  # linha 1 é o cabeçalho
        item = LinhaPlanejada(numero=numero, tutor_nome=linha.get('tutor_nome', ''), animal_nome=linha.get('animal_nome', ''))
        plano.append(item)
        if not item.tutor_nome:
            item.erros.append('nome do tutor em branco')
            continue

        email = normalize_email(linha.get('tutor_email')) or None
        if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            item.erros.append('e-mail inválido')
            email = None
        cpf = _digitos(linha.get('tutor_cpf'))
        if cpf and len(cpf) != 11:
            item.erros.append('CPF precisa ter 11 dígitos')
            cpf = ''
        celular = normalize_phone(linha.get('tutor_celular')) if _digitos(linha.get('tutor_celular')) else None
        if celular and len(celular.lstrip('+')) < 12:
            item.avisos.append('celular sem DDD: ficou de fora')
            celular = None

        existente = None
        for conta, motivo in (
            (contas_por_cpf.get(cpf) if cpf else None, 'CPF'),
            (contas_por_email.get(email) if email else None, 'e-mail'),
        ):
            if conta is None:
                continue
            if conta.clinica_id != clinica_id:
                item.erros.append(
                    f'já existe uma conta com este {motivo} fora da clínica; cadastre este tutor pela tela de tutores'
                )
            existente = existente or conta
        if not existente and celular:
            existente = tutores_da_clinica_por_celular.get(celular)

        chave_tutor = cpf or email or (celular and f'cel:{celular}') or f'nome:{_chave(item.tutor_nome)}'
        if existente:
            item.tutor_acao = 'existente'
            chave_tutor = f'id:{existente.id}'
        elif chave_tutor in vistos_no_arquivo:
            item.tutor_acao = 'repetido'
        else:
            item.tutor_acao = 'novo'

        dados_animal = None
        if item.animal_nome:
            especie_chave = _chave(linha.get('especie'))
            especie_chave = _ESPECIE_ALIASES.get(especie_chave, especie_chave)
            especie = especies.get(especie_chave)
            if not especie_chave:
                item.erros.append('espécie em branco')
            elif not especie:
                item.erros.append(f'espécie "{linha.get("especie")}" não reconhecida (use, por exemplo, Cachorro ou Gato)')
            raca = None
            if especie and linha.get('raca'):
                raca = racas.get((especie.id, _chave(linha.get('raca'))))
                if raca is None:
                    item.avisos.append(f'raça "{linha.get("raca")}" não encontrada: ficou em branco')
            dados_animal = {}
            for campo, conversor in (('sexo', _sexo), ('nascimento', _data), ('peso', _peso), ('castrado', _sim_nao)):
                try:
                    dados_animal[campo] = conversor(linha.get(campo))
                except ValueError as exc:
                    item.erros.append(str(exc))
            dados_animal['species_id'] = especie.id if especie else None
            dados_animal['breed_id'] = raca.id if raca else None
            dados_animal['microchip'] = (linha.get('microchip') or '').strip()[:50] or None

            chave_animal = (chave_tutor, _chave(item.animal_nome))
            ja_tem = (
                (existente and _chave(item.animal_nome) in _animais_existentes(existente.id))
                or chave_animal in animais_no_arquivo
            )
            if ja_tem:
                item.animal_acao = 'existente'
            else:
                item.animal_acao = 'novo'
                if item.ok:
                    animais_no_arquivo.add(chave_animal)

        if item.ok and item.tutor_acao == 'novo':
            vistos_no_arquivo[chave_tutor] = numero
        item.dados = {
            'chave_tutor': chave_tutor,
            'existente_id': existente.id if existente else None,
            'email': email,
            'cpf': normalize_cpf(cpf) if cpf else None,
            'celular': celular,
            'animal': dados_animal,
        }
    return plano


def resumo(plano: list[LinhaPlanejada]) -> dict:
    validas = [item for item in plano if item.ok]
    return {
        'linhas': len(plano),
        'com_erro': len(plano) - len(validas),
        'tutores_novos': sum(1 for item in validas if item.tutor_acao == 'novo'),
        'tutores_existentes': len({item.dados['existente_id'] for item in validas if item.tutor_acao == 'existente'}),
        'animais_novos': sum(1 for item in validas if item.animal_acao == 'novo'),
        'animais_existentes': sum(1 for item in validas if item.animal_acao == 'existente'),
    }


def aplicar(linhas: list[dict], clinica_id: int, autor) -> dict:
    """Grava as linhas válidas; as com erro são ignoradas. Uma transação só."""
    from extensions import db
    from models import Animal, User
    from models.usuarios import build_placeholder_email

    plano = planejar(linhas, clinica_id)
    criados = {}
    for item in plano:
        if not item.ok:
            continue
        dados = item.dados
        if dados['existente_id']:
            tutor = db.session.get(User, dados['existente_id'])
        elif dados['chave_tutor'] in criados:
            tutor = criados[dados['chave_tutor']]
        else:
            tutor = User(
                name=item.tutor_nome[:120],
                email=dados['email'] or build_placeholder_email(),
                email_is_placeholder=not dados['email'],
                role='adotante',
                clinica_id=clinica_id,
                added_by=autor,
                is_private=True,
                phone=dados['celular'],
                cpf=dados['cpf'],
            )
            tutor.set_password(secrets.token_urlsafe(32))
            db.session.add(tutor)
            db.session.flush()
            criados[dados['chave_tutor']] = tutor

        animal = dados.get('animal')
        if animal is not None and item.animal_acao == 'novo':
            novo = Animal(
                name=item.animal_nome[:100],
                species_id=animal['species_id'],
                breed_id=animal['breed_id'],
                sex=animal['sexo'],
                date_of_birth=animal['nascimento'],
                peso=animal['peso'],
                microchip_number=animal['microchip'],
                user_id=tutor.id,
                added_by_id=autor.id,
                clinica_id=clinica_id,
                status='disponível',
                is_alive=True,
                modo='adotado',
            )
            db.session.add(novo)
            if animal['castrado'] is not None:
                novo.neutered = animal['castrado']
            else:
                # "Não informado": o default da coluna (False) diria "não castrado".
                db.session.flush()
                novo.neutered = None
    db.session.commit()
    return resumo(plano)
