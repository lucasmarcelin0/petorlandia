"""Vacinas vencidas ou próximas dos pacientes de uma clínica, e os avisos aos tutores.

Três frentes usam as mesmas regras deste módulo, para nunca discordarem sobre
o que está "atrasado":

- o painel da clínica (lista por tutor, com o botão que abre o WhatsApp da
  própria clínica já com a mensagem pronta);
- o envio automático por e-mail e push, que cada clínica liga quando quiser
  (``Clinica.lembrete_vacina_automatico``, desligado por padrão);
- o botão "enviar agora", que roda o mesmo envio automático só para a clínica.

De onde sai a data de vencimento de uma dose:

- **reforço**: a dose aplicada mais recente de cada grupo de proteção (a mesma
  regra da ficha do paciente: uma antirrábica nova substitui a anterior,
  mesmo de outra marca) + ``intervalo_dias``;
- **agendada**: dose cadastrada como "não aplicada" com data marcada.

Régua do envio automático: 7 dias antes, no dia, 7 dias depois e 30 dias
depois do vencimento. Cada marco sai uma única vez por canal; se o job ficar
uns dias sem rodar, o marco ainda sai em até ``TOLERANCIA_MARCO_DIAS`` dias e
depois é dado como perdido, para não avisar sobre algo antigo de repente.
Atrasos antigos (antes do primeiro dia de uso, por exemplo) nunca disparam
e-mail sozinhos: ficam no painel para a equipe decidir.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import quote

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from time_utils import now_in_brazil

#: Dias em relação ao vencimento em que o tutor recebe o aviso automático.
MARCOS = (-7, 0, 7, 30)

#: Quantos dias depois do marco o aviso ainda pode sair (job parado, falha de
#: SMTP etc.). Menor que o intervalo entre marcos, para nunca acumular dois.
TOLERANCIA_MARCO_DIAS = 6

#: Janela "vence em breve" do painel.
DIAS_FUTUROS_PAINEL = 7

#: Filtros de atraso do painel (0 = todas).
PERIODOS_PAINEL = (30, 90, 365, 0)
PERIODO_PADRAO = 90

#: Uma dose agendada é dada como resolvida se houver aplicação do mesmo grupo
#: até estes dias antes da data marcada (aplicação adiantada lançada como
#: registro novo). Menor que o intervalo das doses do protocolo inicial
#: (21-30 dias), para não esconder a 2ª dose de um filhote.
MARGEM_DOSE_ADIANTADA_DIAS = 7

CANAL_EMAIL = 'email'
CANAL_PUSH = 'push'
CANAL_WHATSAPP = 'whatsapp'
ORIGEM_AUTOMATICO = 'automatico'
ORIGEM_MANUAL = 'manual'

NOTIFICATION_KIND = 'vaccine_overdue'
_SALT_DESCADASTRO = 'lembrete-vacina-sair'
_EMAIL_INTERNO = '@convite.petorlandia.local'


# --------------------------------------------------------------- regras


def grupo_clinico(vacina) -> str:
    """Grupo de proteção da vacina, independente da marca comercial.

    Uma dose posterior de Rabisin/Raiva PM, por exemplo, substitui uma dose
    anterior de Canigen R: as duas são antirrábicas.
    """
    raw = f'{vacina.nome or ""} {vacina.tipo or ""}'.casefold()
    if raw.isascii():
        normalized = raw
    else:
        normalized = ''.join([
            char for char in unicodedata.normalize('NFD', raw)
            if unicodedata.category(char) != 'Mn'
        ])
    if any(token in normalized for token in ('antirrab', 'raiva', 'rabisin', 'defensor', 'hertaliq', 'canigen r')):
        return 'antirrabica'
    if 'leish' in normalized:
        return 'leishmaniose'
    if 'giardia' in normalized:
        return 'giardiase'
    if any(token in normalized for token in ('dhppi', 'vanguard', 'nobivac canine', 'polivalente', 'multipla')):
        return 'multipla'
    return normalized or str(vacina.id)


@dataclass
class Pendencia:
    vacina: object
    animal: object
    vencimento: date
    dias_atraso: int
    origem: str  # 'reforco' ou 'agendada'

    @property
    def situacao(self) -> str:
        if self.dias_atraso > 0:
            return 'atrasada'
        if self.dias_atraso == 0:
            return 'hoje'
        return 'proxima'

    @property
    def descricao_prazo(self) -> str:
        data = self.vencimento.strftime('%d/%m/%Y')
        if self.dias_atraso > 0:
            return f'venceu em {data}'
        if self.dias_atraso == 0:
            return 'vence hoje'
        return f'vence em {data}'


@dataclass
class GrupoTutor:
    tutor: object
    pendencias: list = field(default_factory=list)
    bloqueado: bool = False
    ultimo_whatsapp: object = None

    @property
    def maior_atraso(self) -> int:
        return max(p.dias_atraso for p in self.pendencias)

    @property
    def animais(self) -> list:
        vistos = OrderedDict()
        for p in self.pendencias:
            vistos.setdefault(p.animal.id, p.animal)
        return list(vistos.values())


def _pendencias_do_animal(animal, vacinas, hoje: date) -> list[Pendencia]:
    aplicadas = sorted(
        (v for v in vacinas if v.aplicada and v.aplicada_em),
        key=lambda v: (v.aplicada_em, v.id or 0),
        reverse=True,
    )
    agendadas = [v for v in vacinas if not v.aplicada and v.aplicada_em]

    ultima_por_grupo = {}
    datas_aplicadas_por_grupo = defaultdict(list)
    for vacina in aplicadas:
        grupo = grupo_clinico(vacina)
        ultima_por_grupo.setdefault(grupo, vacina)
        datas_aplicadas_por_grupo[grupo].append(vacina.aplicada_em)

    pendencias = []
    grupos_com_agendamento = set()
    for vacina in agendadas:
        grupo = grupo_clinico(vacina)
        limite = vacina.aplicada_em - timedelta(days=MARGEM_DOSE_ADIANTADA_DIAS)
        if any(data >= limite for data in datas_aplicadas_por_grupo.get(grupo, [])):
            continue  # já aplicada (registro novo lançado no lugar do agendado)
        grupos_com_agendamento.add(grupo)
        pendencias.append(Pendencia(
            vacina=vacina,
            animal=animal,
            vencimento=vacina.aplicada_em,
            dias_atraso=(hoje - vacina.aplicada_em).days,
            origem='agendada',
        ))

    for grupo, vacina in ultima_por_grupo.items():
        if grupo in grupos_com_agendamento:
            continue  # a próxima dose já está marcada; ela é a pendência
        vencimento = vacina.proxima_dose
        if not vencimento:
            continue
        pendencias.append(Pendencia(
            vacina=vacina,
            animal=animal,
            vencimento=vencimento,
            dias_atraso=(hoje - vencimento).days,
            origem='reforco',
        ))
    return pendencias


def pendencias_da_clinica(
    clinica_id: int,
    hoje: date | None = None,
    *,
    atraso_max_dias: int = PERIODO_PADRAO,
    dias_futuros: int = DIAS_FUTUROS_PAINEL,
) -> list[Pendencia]:
    """Doses vencidas (até ``atraso_max_dias``; 0 = sem limite) e as que vencem
    nos próximos ``dias_futuros`` dias, dos pacientes vivos da clínica."""
    from models import Animal, Vacina

    hoje = hoje or now_in_brazil().date()
    animais = (
        Animal.query
        .filter(
            Animal.clinica_id == clinica_id,
            Animal.removido_em.is_(None),
            Animal.falecido_em.is_(None),
            or_(Animal.is_alive.is_(None), Animal.is_alive.is_(True)),
        )
        .all()
    )
    if not animais:
        return []
    por_id = {a.id: a for a in animais}
    vacinas_por_animal = defaultdict(list)
    ids = list(por_id)
    for inicio in range(0, len(ids), 500):
        lote = ids[inicio:inicio + 500]
        for vacina in Vacina.query.filter(Vacina.animal_id.in_(lote)).all():
            vacinas_por_animal[vacina.animal_id].append(vacina)

    resultado = []
    for animal_id, vacinas in vacinas_por_animal.items():
        for pendencia in _pendencias_do_animal(por_id[animal_id], vacinas, hoje):
            if pendencia.dias_atraso < -dias_futuros:
                continue
            if atraso_max_dias and pendencia.dias_atraso > atraso_max_dias:
                continue
            resultado.append(pendencia)
    resultado.sort(key=lambda p: (p.vencimento, p.animal.name or '', p.vacina.nome or ''))
    return resultado


def tutores_bloqueados(user_ids) -> set[int]:
    from models import LembreteVacinaBloqueio

    ids = [uid for uid in set(user_ids) if uid]
    if not ids:
        return set()
    return {
        row[0] for row in db.session.query(LembreteVacinaBloqueio.user_id)
        .filter(LembreteVacinaBloqueio.user_id.in_(ids)).all()
    }


def agrupar_por_tutor(clinica_id: int, pendencias: list[Pendencia]) -> list[GrupoTutor]:
    """Uma entrada por tutor (uma única mensagem para quem tem vários animais)."""
    from models import LembreteVacinaEnvio

    grupos: dict[int, GrupoTutor] = OrderedDict()
    for pendencia in pendencias:
        tutor = pendencia.animal.owner
        if tutor is None:
            continue
        grupos.setdefault(tutor.id, GrupoTutor(tutor=tutor)).pendencias.append(pendencia)
    if not grupos:
        return []

    bloqueados = tutores_bloqueados(grupos)
    ultimos = {}
    rows = (
        db.session.query(LembreteVacinaEnvio.tutor_id, db.func.max(LembreteVacinaEnvio.enviado_em))
        .filter(
            LembreteVacinaEnvio.clinica_id == clinica_id,
            LembreteVacinaEnvio.canal == CANAL_WHATSAPP,
            LembreteVacinaEnvio.tutor_id.in_(list(grupos)),
        )
        .group_by(LembreteVacinaEnvio.tutor_id)
        .all()
    )
    for tutor_id, quando in rows:
        ultimos[tutor_id] = quando
    for tutor_id, grupo in grupos.items():
        grupo.bloqueado = tutor_id in bloqueados
        grupo.ultimo_whatsapp = ultimos.get(tutor_id)
    # Atrasos mais recentes primeiro: quem venceu há pouco tende a voltar.
    return sorted(grupos.values(), key=lambda g: (g.maior_atraso < 0, abs(g.maior_atraso)))


# --------------------------------------------------------------- WhatsApp


def telefone_whatsapp(phone: str | None) -> str | None:
    """Número no formato do wa.me (55 + DDD + número) ou ``None`` se inválido."""
    digitos = re.sub(r'\D', '', phone or '')
    if digitos.startswith('00'):
        digitos = digitos[2:]
    if digitos.startswith('0'):
        digitos = digitos[1:]
    if len(digitos) in (10, 11):
        digitos = '55' + digitos
    if digitos.startswith('55') and len(digitos) in (12, 13):
        return digitos
    return None


def _primeiro_nome(nome: str | None) -> str:
    return (nome or '').strip().split(' ')[0] if (nome or '').strip() else ''


def mensagem_whatsapp(clinica, tutor, pendencias: list[Pendencia]) -> str:
    nome = _primeiro_nome(getattr(tutor, 'name', ''))
    saudacao = f'Olá, {nome}!' if nome else 'Olá!'
    linhas = [
        f'{saudacao} Aqui é da {clinica.nome}. 🐾',
        'Passando para lembrar das vacinas:',
    ]
    for p in pendencias:
        linhas.append(f'• {p.vacina.nome} de {p.animal.name or "seu pet"}: {p.descricao_prazo}')
    linhas.append('Quer agendar a aplicação? É só responder esta mensagem.')
    return '\n'.join(linhas)


def link_whatsapp(phone: str | None, texto: str) -> str | None:
    numero = telefone_whatsapp(phone)
    if not numero:
        return None
    return f'https://wa.me/{numero}?text={quote(texto)}'


def registrar_whatsapp_manual(clinica_id: int, tutor_id: int, vacina_ids, usuario_id: int | None) -> int:
    """Grava o clique da equipe no botão do WhatsApp (sem commit).

    Só aceita doses de animais da clínica e do tutor informado, para que uma
    requisição forjada não registre aviso em paciente de outra clínica.
    """
    from models import Animal, LembreteVacinaEnvio, Vacina

    ids = {int(v) for v in vacina_ids or [] if str(v).isdigit()}
    if not ids:
        return 0
    hoje = now_in_brazil().date()
    vacinas = (
        Vacina.query.join(Animal, Vacina.animal_id == Animal.id)
        .filter(Vacina.id.in_(ids), Animal.clinica_id == clinica_id, Animal.user_id == tutor_id)
        .all()
    )
    for vacina in vacinas:
        vencimento = (vacina.proxima_dose if vacina.aplicada else vacina.aplicada_em) or hoje
        db.session.add(LembreteVacinaEnvio(
            clinica_id=clinica_id,
            animal_id=vacina.animal_id,
            vacina_id=vacina.id,
            tutor_id=tutor_id,
            vencimento=vencimento,
            canal=CANAL_WHATSAPP,
            origem=ORIGEM_MANUAL,
            marco=(hoje - vencimento).days,
            enviado_por_id=usuario_id,
        ))
    return len(vacinas)


# --------------------------------------------------------------- descadastro


def _serializer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=_SALT_DESCADASTRO)


def token_descadastro(user_id: int) -> str:
    return _serializer().dumps(int(user_id))


def user_id_do_token(token: str) -> int | None:
    try:
        value = _serializer().loads(token)
    except BadSignature:
        return None
    return value if isinstance(value, int) else None


def bloquear_tutor(user_id: int) -> bool:
    """Registra o descadastro (sem commit). Retorna False se já estava."""
    from models import LembreteVacinaBloqueio

    if LembreteVacinaBloqueio.query.filter_by(user_id=user_id).first():
        return False
    db.session.add(LembreteVacinaBloqueio(user_id=user_id))
    return True


def desbloquear_tutor(user_id: int) -> bool:
    from models import LembreteVacinaBloqueio

    return bool(LembreteVacinaBloqueio.query.filter_by(user_id=user_id).delete())


# --------------------------------------------------------------- envio automático


def marco_atual(dias_atraso: int) -> int | None:
    """Marco da régua a avisar hoje, ou ``None`` se não há aviso pendente."""
    for marco in sorted(MARCOS, reverse=True):
        if dias_atraso >= marco:
            return marco if dias_atraso - marco <= TOLERANCIA_MARCO_DIAS else None
    return None


def _chave(vacina_id: int, vencimento: date, marco: int, canal: str) -> str:
    return f'{vacina_id}:{vencimento.isoformat()}:{marco}:{canal}'


def _email_valido(user) -> str | None:
    email = (getattr(user, 'email', '') or '').strip()
    if not email or email.endswith(_EMAIL_INTERNO) or getattr(user, 'email_is_placeholder', False):
        return None
    return email


def _base_url() -> str:
    return os.environ.get('FRONTEND_URL', 'https://www.petorlandia.com.br').rstrip('/')


def _assunto(pendencias: list[Pendencia]) -> str:
    animais = []
    for p in pendencias:
        nome = p.animal.name or 'seu pet'
        if nome not in animais:
            animais.append(nome)
    alvo = animais[0] if len(animais) == 1 else ', '.join(animais[:-1]) + ' e ' + animais[-1]
    if any(p.dias_atraso > 0 for p in pendencias):
        return f'Vacina atrasada: {alvo}'
    return f'Lembrete de vacina: {alvo}'


def _corpo_email(clinica, tutor, pendencias: list[Pendencia]) -> str:
    nome = _primeiro_nome(getattr(tutor, 'name', ''))
    linhas = [
        f'Olá{", " + nome if nome else ""}!',
        '',
        f'A {clinica.nome} lembra das vacinas dos seus pets:',
        '',
    ]
    for p in pendencias:
        linhas.append(f'• {p.vacina.nome} de {p.animal.name or "seu pet"}: {p.descricao_prazo}')
    linhas += ['', 'Manter as vacinas em dia protege o seu pet e a sua família.', '']
    contato = []
    if getattr(clinica, 'telefone', None):
        contato.append(f'telefone {clinica.telefone}')
        wa = telefone_whatsapp(clinica.telefone)
        if wa:
            contato.append(f'WhatsApp https://wa.me/{wa}')
    if getattr(clinica, 'email', None):
        contato.append(f'e-mail {clinica.email}')
    if contato:
        linhas.append(f'Para agendar, fale com a {clinica.nome}: ' + ' · '.join(contato) + '.')
    else:
        linhas.append(f'Para agendar, fale com a {clinica.nome}.')
    linhas += [
        '',
        'Não quer mais receber estes lembretes? Acesse:',
        f'{_base_url()}/lembretes-vacina/sair/{token_descadastro(tutor.id)}',
    ]
    return '\n'.join(linhas)


def _ja_enviadas(chaves) -> set[str]:
    from models import LembreteVacinaEnvio

    chaves = list(chaves)
    if not chaves:
        return set()
    return {
        row[0] for row in db.session.query(LembreteVacinaEnvio.chave)
        .filter(LembreteVacinaEnvio.chave.in_(chaves)).all()
    }


def _registrar(clinica_id, tutor_id, itens, canal, enviado_por_id):
    from models import LembreteVacinaEnvio

    for pendencia, marco in itens:
        db.session.add(LembreteVacinaEnvio(
            clinica_id=clinica_id,
            animal_id=pendencia.animal.id,
            vacina_id=pendencia.vacina.id,
            tutor_id=tutor_id,
            vencimento=pendencia.vencimento,
            canal=canal,
            origem=ORIGEM_AUTOMATICO,
            marco=marco,
            enviado_por_id=enviado_por_id,
            chave=_chave(pendencia.vacina.id, pendencia.vencimento, marco, canal),
        ))


def enviar_lembretes_da_clinica(clinica, hoje: date | None = None, enviado_por_id: int | None = None) -> dict:
    """Envia por e-mail e push os marcos de hoje dos tutores da clínica.

    Um e-mail e um push por tutor, listando todas as doses que atingiram um
    marco. Só registra o canal que de fato saiu; o que falhou tenta de novo
    no dia seguinte, dentro da tolerância do marco.
    """
    from models import Notification
    from services.notifications import _send_email
    from services.push import push_to_user

    hoje = hoje or now_in_brazil().date()
    resumo = {'tutores': 0, 'emails': 0, 'push': 0}
    atraso_max = max(MARCOS) + TOLERANCIA_MARCO_DIAS
    pendencias = pendencias_da_clinica(
        clinica.id, hoje, atraso_max_dias=atraso_max, dias_futuros=-min(MARCOS),
    )
    por_tutor = defaultdict(list)
    for pendencia in pendencias:
        marco = marco_atual(pendencia.dias_atraso)
        tutor = pendencia.animal.owner
        if marco is None or tutor is None:
            continue
        por_tutor[tutor.id].append((pendencia, marco))
    if not por_tutor:
        return resumo

    bloqueados = tutores_bloqueados(por_tutor)
    for tutor_id, itens in por_tutor.items():
        if tutor_id in bloqueados:
            continue
        tutor = itens[0][0].animal.owner
        chaves = [_chave(p.vacina.id, p.vencimento, m, c) for p, m in itens for c in (CANAL_EMAIL, CANAL_PUSH)]
        enviadas = _ja_enviadas(chaves)
        enviou_algo = False

        email = _email_valido(tutor)
        itens_email = [
            (p, m) for p, m in itens if _chave(p.vacina.id, p.vencimento, m, CANAL_EMAIL) not in enviadas
        ]
        if email and itens_email:
            lista = [p for p, _ in itens_email]
            corpo = _corpo_email(clinica, tutor, lista)
            if _send_email([email], _assunto(lista), corpo):
                _registrar(clinica.id, tutor_id, itens_email, CANAL_EMAIL, enviado_por_id)
                db.session.add(Notification(
                    user_id=tutor_id, message=corpo, channel='email', kind=NOTIFICATION_KIND,
                ))
                resumo['emails'] += 1
                enviou_algo = True

        itens_push = [
            (p, m) for p, m in itens if _chave(p.vacina.id, p.vencimento, m, CANAL_PUSH) not in enviadas
        ]
        if itens_push:
            lista = [p for p, _ in itens_push]
            texto = f'{clinica.nome}: ' + '; '.join(
                f'{p.vacina.nome} de {p.animal.name or "seu pet"} {p.descricao_prazo}' for p in lista
            )
            try:
                enviados = push_to_user(tutor_id, 'Lembrete de vacina 🐾', texto, url='/', tag='lembrete-vacina')
            except Exception:  # noqa: BLE001 - push é best-effort
                current_app.logger.exception('[Vacinas atrasadas] Falha no push do tutor %s.', tutor_id)
                enviados = 0
            if enviados:
                _registrar(clinica.id, tutor_id, itens_push, CANAL_PUSH, enviado_por_id)
                resumo['push'] += 1
                enviou_algo = True

        if enviou_algo:
            resumo['tutores'] += 1
            try:
                db.session.commit()
            except IntegrityError:
                # Outro processo registrou o mesmo marco ao mesmo tempo; o
                # aviso já saiu por lá.
                db.session.rollback()
    return resumo


def enviar_lembretes_automaticos(hoje: date | None = None) -> dict:
    """Job diário: roda o envio para cada clínica ativa que ligou a opção."""
    from models import Clinica

    total = {'clinicas': 0, 'tutores': 0, 'emails': 0, 'push': 0}
    clinicas = (
        Clinica.query
        .filter(Clinica.lembrete_vacina_automatico.is_(True), Clinica.status == 'ativa')
        .all()
    )
    for clinica in clinicas:
        try:
            resumo = enviar_lembretes_da_clinica(clinica, hoje)
        except Exception:  # noqa: BLE001 - uma clínica não derruba as demais
            db.session.rollback()
            current_app.logger.exception('[Vacinas atrasadas] Falha na clínica %s.', clinica.id)
            continue
        total['clinicas'] += 1
        for chave in ('tutores', 'emails', 'push'):
            total[chave] += resumo[chave]
    return total
