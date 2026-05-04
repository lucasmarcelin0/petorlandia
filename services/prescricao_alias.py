"""
Serviço de resolução de aliases de prescrição.

Mapeia o texto exato de prescrições históricas ao medicamento canônico no banco,
usando múltiplas estratégias de correspondência em ordem de confiança decrescente.

Estratégias (em cascata):
  1. exato      — nome_prescrito == nome do medicamento (case-insensitive, trimmed)
  2. normalizado — mesmo após converter em-dash (–) → hífen (-) e normalizar espaços
  3. prefixo    — parte antes do separador dash coincide com nome do medicamento
  4. variante   — parte inicial coincide com nome_variante de uma apresentação
  5. substring  — nome do medicamento está contido no início da prescrição

Se nenhuma estratégia encontrar resultado, registra 'sem_match' para evitar buscas
repetidas na mesma prescrição.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import text as sql_text


# ─────────────────────────── normalização ───────────────────────────

_DASHES = (
    '–',  # en-dash  –
    '—',  # em-dash  —
    '−',  # minus    −
    '―',  # horizontal bar ―
    '‐',  # hyphen ‐
    '‑',  # non-breaking hyphen ‑
)


def _norm(s: str) -> str:
    """Lowercase, substitui dashes por hífen, colapsa espaços."""
    if not s:
        return ''
    for d in _DASHES:
        s = s.replace(d, '-')
    s = s.lower().strip()
    s = re.sub(r'\s*-+\s*', ' - ', s)   # espaços uniformes ao redor do hífen
    s = re.sub(r'\s+', ' ', s)
    return s


def _prefixo(nome: str) -> str:
    """Extrai a parte antes do primeiro separador ' - '.
    'Dipirona - 500 mg/mL, gotas'  →  'dipirona'
    'Tobradex - Tobramicina 0,3%'  →  'tobradex'
    """
    norm = _norm(nome)
    m = re.match(r'^(.+?)\s+-\s+', norm)
    return m.group(1).strip() if m else norm


# ─────────────────────────── resolução ──────────────────────────────

def resolver_alias(nome_prescrito: str, session) -> tuple[Optional[int], str]:
    """
    Tenta resolver nome_prescrito para um medicamento_id.
    Retorna (medicamento_id, confianca) — medicamento_id pode ser None.

    O resultado NÃO é gravado aqui; o chamador decide se persiste.
    """
    nome = nome_prescrito.strip()
    if not nome:
        return None, 'sem_match'

    norm = _norm(nome)
    prefixo = _prefixo(nome)

    # ── Estratégia 1: match exato (case-insensitive) ──────────────────
    row = session.execute(sql_text(
        "SELECT id FROM medicamento WHERE lower(trim(nome)) = :n LIMIT 1"
    ), {'n': nome.lower().strip()}).fetchone()
    if row:
        return row[0], 'exato'

    # ── Estratégia 2: match após normalizar dashes ────────────────────
    row = session.execute(sql_text(
        """SELECT id FROM medicamento
           WHERE lower(
               regexp_replace(trim(nome),
                   E'[\\u2013\\u2014\\u2212\\u2010\\u2011\\u2015]', '-', 'g')
           ) = :n
           LIMIT 1"""
    ), {'n': norm}).fetchone()
    if row:
        return row[0], 'normalizado'

    # ── Estratégia 3: prefixo (parte antes do dash) ───────────────────
    if prefixo and prefixo != norm:
        row = session.execute(sql_text(
            """SELECT id FROM medicamento
               WHERE lower(trim(nome)) = :p
                  OR lower(trim(nome)) LIKE :plike
               ORDER BY
                   CASE WHEN lower(trim(nome)) = :p THEN 0 ELSE 1 END,
                   length(nome)
               LIMIT 1"""
        ), {'p': prefixo, 'plike': prefixo + '%'}).fetchone()
        if row:
            return row[0], 'prefixo'

    # ── Estratégia 4: nome_variante nas apresentações ─────────────────
    # Tenta o prefixo ou o nome completo normalizado
    for busca in [prefixo, norm.split(' - ')[0]]:
        if not busca or len(busca) < 4:
            continue
        row = session.execute(sql_text(
            """SELECT medicamento_id FROM apresentacao_medicamento
               WHERE lower(nome_variante) LIKE :b
               LIMIT 1"""
        ), {'b': busca + '%'}).fetchone()
        if row:
            return row[0], 'variante'

    # ── Estratégia 5: substring — nome do medicamento aparece no início da prescrição
    row = session.execute(sql_text(
        """SELECT id FROM medicamento
           WHERE length(trim(nome)) >= 6
             AND lower(:full) LIKE lower(trim(nome)) || '%'
           ORDER BY length(nome) DESC
           LIMIT 1"""
    ), {'full': norm}).fetchone()
    if row:
        return row[0], 'substring'

    return None, 'sem_match'


# ─────────────────────── API pública (com cache) ─────────────────────

def resolver_e_persistir(nome_prescrito: str, session, db) -> Optional[int]:
    """
    Retorna o medicamento_id para nome_prescrito, gravando o resultado na tabela
    prescricao_alias_medicamento para consultas futuras (sem nova busca).
    """
    from models.base import PrescricaoAliasMedicamento
    from sqlalchemy.exc import IntegrityError

    nome = nome_prescrito.strip()

    # Verifica cache primeiro
    alias = PrescricaoAliasMedicamento.query.filter_by(nome_prescrito=nome).first()
    if alias is not None:
        return alias.medicamento_id  # pode ser None (sem_match confirmado)

    med_id, confianca = resolver_alias(nome, session)

    try:
        novo = PrescricaoAliasMedicamento(
            nome_prescrito=nome,
            medicamento_id=med_id,
            confianca=confianca,
        )
        session.add(novo)
        session.flush()
    except IntegrityError:
        session.rollback()
        # Outra thread resolveu ao mesmo tempo — relê
        alias = PrescricaoAliasMedicamento.query.filter_by(nome_prescrito=nome).first()
        return alias.medicamento_id if alias else med_id

    return med_id


def popular_aliases_frequentes(session, db, user_id: int, limite: int = 50) -> dict:
    """
    Resolve e persiste aliases para os `limite` medicamentos mais prescritos
    pelo user_id fornecido. Retorna estatísticas de resolução.
    """
    rows = session.execute(sql_text("""
        SELECT p.medicamento, COUNT(*) AS total
        FROM prescricao p
        JOIN bloco_prescricao bp ON bp.id = p.bloco_id
        WHERE bp.saved_by_id = :uid
        GROUP BY p.medicamento
        ORDER BY total DESC
        LIMIT :lim
    """), {'uid': user_id, 'lim': limite}).fetchall()

    stats = {'total': len(rows), 'resolvidos': 0, 'sem_match': 0}
    for nome, _ in rows:
        med_id = resolver_e_persistir(nome, session, db)
        if med_id:
            stats['resolvidos'] += 1
        else:
            stats['sem_match'] += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return stats
