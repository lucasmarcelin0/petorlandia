"""Régua dos anúncios de adoção: foto, telefone e confirmação mensal.

Quem anuncia um animal para adoção costuma esquecer o anúncio no ar. As três
frentes abaixo compartilham as regras deste módulo, para nunca discordarem
sobre qual anúncio está "vencido":

- o e-mail único pedindo foto e telefone, que são o que faz alguém se
  interessar e o que permite avisar o responsável;
- a pergunta mensal por e-mail ("ainda está para adoção?");
- a mesma pergunta em pop-up quando o responsável volta ao site;
- a saída automática da lista quando a pergunta fica sem resposta: o animal
  passa a "adotado" e deixa a vitrine, mas a pergunta continua de pé e um
  "ainda disponível" devolve o anúncio à lista.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from flask import current_app

from extensions import db
from time_utils import BR_TZ, now_in_brazil

ADOPTION_MODE = 'doação'

#: Dias sem confirmação até perguntar de novo se o animal segue disponível.
REVIEW_INTERVAL_DAYS = 30

#: Prazo de resposta depois da pergunta. Sem confirmação até lá o anúncio sai
#: da lista sozinho, para a vitrine não acumular animal que já tem dono.
EXPIRY_GRACE_DAYS = 15

#: Carência antes de pedir foto e telefone: dá tempo de a pessoa terminar o
#: cadastro sozinha antes de receber uma cobrança.
DATA_REQUEST_GRACE_HOURS = 12

REVIEW_PATH = '/adocao/revisar'

KIND_REVIEW = 'adoption_listing_review'
KIND_DATA_REQUEST = 'adoption_listing_incomplete'
KIND_EXPIRED = 'adoption_listing_expired'


def _as_brazil(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BR_TZ)
    return value.astimezone(BR_TZ)


def _days_since(value, now):
    moment = _as_brazil(value)
    if moment is None:
        return None
    return (_as_brazil(now).date() - moment.date()).days


def adoption_listings_query():
    """Anúncios de adoção no ar: nem removidos, nem de animal falecido."""
    from models import Animal

    return Animal.query.filter(
        Animal.modo == ADOPTION_MODE,
        Animal.removido_em.is_(None),
        Animal.is_alive.isnot(False),
    )


def listings_of(user):
    from models import Animal

    return (
        adoption_listings_query()
        .filter(Animal.user_id == user.id)
        .order_by(Animal.date_added, Animal.id)
        .all()
    )


def expired_listings_of(user):
    """Anúncios que saíram da lista por falta de resposta e seguem sem ela."""
    from models import Animal

    return (
        Animal.query.filter(
            Animal.user_id == user.id,
            Animal.modo == 'adotado',
            Animal.adocao_expirada_em.isnot(None),
            Animal.removido_em.is_(None),
            Animal.is_alive.isnot(False),
        )
        .order_by(Animal.date_added, Animal.id)
        .all()
    )


def ensure_own_adoption_listings(user, animal_ids):
    """Devolve só os anúncios de adoção de ``user`` entre ``animal_ids``.

    É o ponto único de autorização da revisão: id de animal de outra pessoa,
    removido ou que nunca esteve para adoção é descartado aqui, antes de
    qualquer alteração.
    """
    wanted = {int(value) for value in animal_ids if str(value).isdigit()}
    if not wanted or user is None:
        return []
    own = listings_of(user) + expired_listings_of(user)
    return [animal for animal in own if animal.id in wanted]


def days_listed(animal, now=None):
    """Dias desde a última confirmação (ou desde o cadastro, se nunca houve)."""
    return _days_since(animal.adocao_revisada_em or animal.date_added, now or now_in_brazil())


def is_review_due(animal, now=None):
    days = days_listed(animal, now)
    # Sem data nenhuma o anúncio é antigo o bastante para valer a pergunta.
    return days is None or days >= REVIEW_INTERVAL_DAYS


def review_deadline(animal):
    """Último dia para responder antes de o anúncio sair da lista, ou ``None``.

    O prazo conta de quando a pergunta foi aberta neste ciclo
    (``adocao_lembrete_em``): o envio do e-mail ou, para quem não tem e-mail
    utilizável, o dia em que o job registrou que o pop-up passou a perguntar.
    Sem esse registro não há prazo — anúncio antigo nunca some sem aviso.
    """
    clock = _as_brazil(animal.adocao_revisada_em or animal.date_added)
    asked = _as_brazil(animal.adocao_lembrete_em)
    # Registro anterior à última confirmação é de um ciclo já respondido.
    if asked is None or (clock is not None and asked < clock):
        return None
    return asked.date() + timedelta(days=EXPIRY_GRACE_DAYS)


def pending_reviews(user, now=None):
    """O que o pop-up pergunta: anúncios vencidos e os que já saíram da lista."""
    now = now or now_in_brazil()
    due = [animal for animal in listings_of(user) if is_review_due(animal, now)]
    return due + expired_listings_of(user)


def has_photo(animal):
    return bool((animal.image or '').strip())


def needs_phone(user):
    return not (getattr(user, 'phone', None) or '').strip()


def confirm_still_available(animal, now=None):
    """Resposta "ainda disponível": renova o anúncio ou o devolve à lista."""
    if animal.modo != ADOPTION_MODE:
        animal.modo = ADOPTION_MODE
        animal.status = 'disponível'
    animal.adocao_expirada_em = None
    animal.adocao_revisada_em = now or now_in_brazil()


def mark_adopted(animal, now=None):
    """Tira o anúncio do ar; o histórico do animal continua com o responsável."""
    animal.modo = 'adotado'
    animal.status = 'indisponível'
    animal.adocao_expirada_em = None
    animal.adocao_revisada_em = now or now_in_brazil()


def expire_listing(animal, now=None):
    """Prazo vencido sem resposta: sai da lista, mas a pergunta continua."""
    animal.modo = 'adotado'
    animal.status = 'indisponível'
    animal.adocao_expirada_em = now or now_in_brazil()


def review_cards(animals, now=None):
    """Dados simples para a tela e o pop-up.

    O pop-up fica em cache entre requests; instância ORM guardada lá chega
    desanexada na navegação seguinte e derruba o layout inteiro.
    """
    now = now or now_in_brazil()
    cards = []
    for animal in animals:
        expired = _as_brazil(animal.adocao_expirada_em) if animal.modo != ADOPTION_MODE else None
        cards.append({
            'id': animal.id,
            'name': (animal.name or '').strip() or 'Sem nome',
            'image': animal.image if has_photo(animal) else None,
            'days': _days_since(animal.date_added, now),
            'expired_on': expired.date() if expired else None,
            'deadline': (
                review_deadline(animal)
                if not expired and is_review_due(animal, now) else None
            ),
        })
    return cards


def can_email(user):
    """Só contas de gente de verdade, com endereço que recebe mensagem."""
    if user is None or getattr(user, 'is_test_account', False):
        return False
    email = (getattr(user, 'email_informado', '') or '').strip().lower()
    # cadastro.* e convite.* são identificadores internos como o da campanha.
    return bool(email) and not email.endswith('petorlandia.local')


def _base_url():
    # Import tardio: app.py importa os blueprints, que importam este módulo.
    from app import _notification_base_url

    return _notification_base_url()


def _first_name(user):
    return (getattr(user, 'name', '') or '').split(' ')[0] or 'tudo bem'


def join_names(names):
    """``['Mel', 'Luna', 'Pirata']`` -> ``'Mel, Luna e Pirata'``."""
    names = [(name or '').strip() or 'seu animal' for name in names]
    if len(names) <= 1:
        return ''.join(names)
    return f"{', '.join(names[:-1])} e {names[-1]}"


def _join_names(animals):
    return join_names(animal.name for animal in animals)


def _missing_data_lines(owner, without_photo):
    lines = []
    if without_photo:
        verbo = 'está' if len(without_photo) == 1 else 'estão'
        lines.append(
            f'- Foto: {_join_names(without_photo)} ainda {verbo} sem foto. Anúncio '
            'com foto chama muito mais a atenção de quem quer adotar.'
        )
    if needs_phone(owner):
        lines.append(
            '- Telefone: seu cadastro está sem telefone. Com ele fica mais fácil '
            'avisar você quando alguém quiser adotar.'
        )
    return lines


def build_review_email(owner, due, listings=None, now=None):
    """Pergunta mensal: o anúncio ainda vale?

    ``listings`` são todos os anúncios do responsável: a mensagem aproveita
    para lembrar da foto que falta em qualquer um deles, não só nos vencidos.
    """
    nomes = _join_names(due)
    link = f'{_base_url()}{REVIEW_PATH}'
    if len(due) == 1:
        dias = _days_since(due[0].date_added, now or now_in_brazil())
        tempo = f' há {dias} dias' if dias else ''
        assunto = f'{nomes} ainda está para adoção? — PetOrlândia'
        abertura = (
            f'{nomes} está no PetOrlândia para adoção{tempo}. O anúncio ainda '
            f'vale ou {nomes} já encontrou um lar?'
        )
    else:
        assunto = f'{nomes} ainda estão para adoção? — PetOrlândia'
        abertura = (
            f'{nomes} estão no PetOrlândia para adoção há mais de um mês. Os '
            'anúncios ainda valem ou algum deles já encontrou um lar?'
        )

    prazo = _as_brazil(now or now_in_brazil()).date() + timedelta(days=EXPIRY_GRACE_DAYS)
    if len(due) == 1:
        sem_resposta = (
            f'Se não tivermos resposta até {prazo:%d/%m}, vamos entender que '
            f'{nomes} já foi adotado e o anúncio sai da lista.'
        )
    else:
        sem_resposta = (
            f'Se não tivermos resposta até {prazo:%d/%m}, vamos entender que '
            'eles já foram adotados e os anúncios saem da lista.'
        )

    partes = [
        f'Olá {_first_name(owner)}!',
        abertura,
        f'Responda por aqui, leva menos de um minuto:\n{link}',
        (
            '- Se ainda está para adoção, o anúncio continua no ar por mais um '
            'mês e você pode aproveitar para colocar uma foto nova.\n'
            '- Se já foi adotado, tiramos o anúncio da lista.'
        ),
        (
            f'{sem_resposta} Se isso acontecer e a adoção ainda não tiver saído, '
            'é só responder depois e o anúncio volta.'
        ),
    ]
    faltas = _missing_data_lines(owner, [a for a in (listings or due) if not has_photo(a)])
    if faltas:
        partes.append('Aproveite para completar o anúncio:\n' + '\n'.join(faltas))
    return assunto, '\n\n'.join(partes)


def build_expired_email(owner, expired):
    """Aviso de que o anúncio saiu da lista por falta de resposta."""
    nomes = _join_names(expired)
    link = f'{_base_url()}{REVIEW_PATH}'
    if len(expired) == 1:
        abertura = (
            f'Perguntamos se {nomes} ainda estava para adoção e não tivemos '
            'resposta, então tiramos o anúncio da lista. O cadastro continua na '
            'sua conta, nada foi apagado.'
        )
        volta = (
            f'Se {nomes} ainda está para adoção, é só avisar por aqui que o '
            f'anúncio volta para a lista:\n{link}'
        )
    else:
        abertura = (
            f'Perguntamos se {nomes} ainda estavam para adoção e não tivemos '
            'resposta, então tiramos os anúncios da lista. Os cadastros '
            'continuam na sua conta, nada foi apagado.'
        )
        volta = (
            'Se algum deles ainda está para adoção, é só avisar por aqui que o '
            f'anúncio volta para a lista:\n{link}'
        )
    return (
        f'Tiramos {nomes} da lista de adoção — PetOrlândia',
        '\n\n'.join([f'Olá {_first_name(owner)}!', abertura, volta]),
    )


def build_data_request_email(owner, animals):
    """Pedido único de foto e telefone, logo depois do cadastro."""
    nomes = _join_names(animals)
    link = f'{_base_url()}{REVIEW_PATH}'
    faltas = _missing_data_lines(owner, [a for a in animals if not has_photo(a)])
    partes = [
        f'Olá {_first_name(owner)}!',
        (
            f'Obrigado por anunciar {nomes} para adoção no PetOrlândia. Para o '
            'anúncio funcionar de verdade, falta pouco:'
        ),
        '\n'.join(faltas),
        f'Dá para resolver tudo na mesma tela, em um minuto:\n{link}',
        (
            'Se a adoção já aconteceu, é só marcar na mesma tela e o anúncio '
            'sai da lista.'
        ),
    ]
    return f'Complete o anúncio de {nomes} — PetOrlândia', '\n\n'.join(partes)


def _deliver(owner, subject, body, *, kind):
    """Envia e deixa o registro; devolve ``False`` se o e-mail não saiu."""
    from models import Notification
    from services.notifications import _send_email

    if not _send_email([owner.email_informado], subject, body):
        return False
    db.session.add(Notification(user_id=owner.id, message=body, channel='email', kind=kind))
    return True


def enviar_lembretes_adocao(now=None):
    """Job diário: no máximo um e-mail por responsável a cada execução.

    Primeiro tira da lista quem não respondeu no prazo. Depois, a pergunta
    mensal tem prioridade e já leva o pedido de foto/telefone junto, para
    ninguém receber duas mensagens no mesmo dia. Só marca o envio quando o
    e-mail saiu: uma falha de SMTP é tentada de novo no dia seguinte.
    """
    from models import Animal

    now = now or now_in_brazil()
    grace_limit = _as_brazil(now) - timedelta(hours=DATA_REQUEST_GRACE_HOURS)
    by_owner = defaultdict(list)
    for animal in adoption_listings_query().order_by(Animal.user_id, Animal.date_added, Animal.id).all():
        by_owner[animal.user_id].append(animal)

    today = _as_brazil(now).date()
    sent = {KIND_REVIEW: 0, KIND_DATA_REQUEST: 0, KIND_EXPIRED: 0}
    for animals in by_owner.values():
        owner = animals[0].owner
        emailable = can_email(owner)

        overdue = []
        for animal in animals:
            deadline = review_deadline(animal)
            if deadline is not None and deadline < today and is_review_due(animal, now):
                overdue.append(animal)
        if overdue:
            # Sai da lista mesmo que o aviso não chegue: a vitrine não pode
            # depender do SMTP, e o pop-up segue perguntando na volta ao site.
            for animal in overdue:
                expire_listing(animal, now)
            sent[KIND_EXPIRED] += len(overdue)
            if emailable:
                subject, body = build_expired_email(owner, overdue)
                _deliver(owner, subject, body, kind=KIND_EXPIRED)
            db.session.commit()
            continue

        due = [animal for animal in animals if is_review_due(animal, now)]
        if not emailable:
            # Sem e-mail utilizável a pergunta existe só no pop-up. Registrar
            # que ela foi aberta é o que dá a essa pessoa o mesmo prazo de
            # todo mundo, em vez de o anúncio sumir no primeiro dia.
            unasked = [animal for animal in due if review_deadline(animal) is None]
            for animal in unasked:
                animal.adocao_lembrete_em = now
            if unasked:
                db.session.commit()
            continue

        last_review_email = [
            _days_since(animal.adocao_lembrete_em, now)
            for animal in animals
            if animal.adocao_lembrete_em is not None
        ]
        review_allowed = not last_review_email or min(last_review_email) >= REVIEW_INTERVAL_DAYS

        if due and review_allowed:
            subject, body = build_review_email(owner, due, animals, now)
            if _deliver(owner, subject, body, kind=KIND_REVIEW):
                for animal in due:
                    animal.adocao_lembrete_em = now
                for animal in animals:
                    animal.adocao_pedido_dados_em = animal.adocao_pedido_dados_em or now
                sent[KIND_REVIEW] += 1
            db.session.commit()
            continue

        fresh = [
            animal for animal in animals
            if animal.adocao_pedido_dados_em is None
            and (_as_brazil(animal.date_added) or grace_limit) <= grace_limit
        ]
        if fresh and (needs_phone(owner) or any(not has_photo(animal) for animal in fresh)):
            subject, body = build_data_request_email(owner, fresh)
            if _deliver(owner, subject, body, kind=KIND_DATA_REQUEST):
                for animal in fresh:
                    animal.adocao_pedido_dados_em = now
                sent[KIND_DATA_REQUEST] += 1
            db.session.commit()

    current_app.logger.info(
        '[Adoção] %s pergunta(s) mensal(is), %s pedido(s) de foto/telefone, '
        '%s anúncio(s) fora da lista por falta de resposta',
        sent[KIND_REVIEW],
        sent[KIND_DATA_REQUEST],
        sent[KIND_EXPIRED],
    )
    return sent
