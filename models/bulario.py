"""Bulário de medicamentos: monografias, apresentações e doses.

Extraído de models/base.py na modularização (2026-07-10).
"""
try:
    from extensions import db
except ImportError:
    from .extensions import db

from flask_login import UserMixin
from flask import url_for, request, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta, timezone
import json
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_CEILING
import unicodedata
import enum
import uuid
from sqlalchemy import Enum, event, func, case, inspect
from enum import Enum
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import synonym, object_session, deferred, validates
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.exc import OperationalError, ProgrammingError
from cryptography.fernet import InvalidToken
from functools import lru_cache
try:
    from document_utils import format_cnpj
except ImportError:
    from ..document_utils import format_cnpj
from time_utils import utcnow, now_in_brazil
from security.crypto import (
    MissingMasterKeyError,
    decrypt_text,
    decrypt_text_for_clinic,
    encrypt_text,
    looks_encrypted_text,
)




class Medicamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    classificacao = db.Column(db.String(100))  # 🆕 antibiótico, anti-inflamatório, etc.
    principio_ativo = db.Column(db.String(100))  # opcional
    via_administracao = db.Column(db.String(50))  # oral, IM, IV...
    dosagem_recomendada = db.Column(db.Text)  # Ex: 5 mg/kg SID
    frequencia = db.Column(db.Text)  # Ex: SID, BID, TID
    duracao_tratamento = db.Column(db.Text)  # Ex: 7 dias
    observacoes = db.Column(db.Text)  # para contraindicações, interações, etc.
    bula = db.Column(db.Text)  # 🆕 Texto completo da bula, opcional
    conteudo_estruturado = db.Column(db.JSON)  # seções clínicas separadas para UI

    # Sinaliza para quais espécies este item é mais relevante.
    # Valores: 'CG' (cães/gatos), 'BE' (bovinos/equinos), 'AMBOS', 'OUTRO'.
    # NULL = não classificado. Usado APENAS para re-ranquear a busca; nenhum item
    # é escondido ou filtrado por causa deste campo.
    species_scope = db.Column(db.String(20), index=True, nullable=True)

    # Produto "canônico" no VetSmart que representa este PA
    # (ex.: "Prednisona" PA genérico, id=1970)
    vetsmart_produto_id = db.Column(db.Integer, index=True)

    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
    )

    apresentacoes = db.relationship('ApresentacaoMedicamento', backref='medicamento', cascade='all, delete-orphan')
    doses = db.relationship('DoseMedicamento', backref='medicamento', cascade='all, delete-orphan', order_by='DoseMedicamento.id')

    def __str__(self):
        return self.nome


class ApresentacaoMedicamento(db.Model):
    __tablename__ = 'apresentacao_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    medicamento_id = db.Column(db.Integer, db.ForeignKey('medicamento.id'), nullable=False)

    forma = db.Column(db.String(50), nullable=False)          # cápsula, líquido, etc.
    concentracao = db.Column(db.String(100), nullable=False)  # Ex: 50 mg/mL, 500 mg/cápsula

    # Campos numéricos para cálculo de dose
    nome_variante        = db.Column(db.String(100))          # "Advocate Cães até 4 kg"
    concentracao_valor   = db.Column(db.Numeric(12, 3))       # 250
    concentracao_unidade = db.Column(db.String(20))           # 'mg' | 'mg/ml' | 'UI' | '%'
    volume_valor         = db.Column(db.Numeric(12, 3))       # 10 (un) ou 50 (ml)
    volume_unidade       = db.Column(db.String(20))           # 'un' | 'ml' | 'g'

    # Nome do produto comercial associado (ex: "Sec Lac" para metergolina Agener).
    # Quando preenchido, permite busca pelo nome comercial no autocomplete e
    # exibe apenas as apresentações desta marca ao pesquisar por ela.
    nome_comercial       = db.Column(db.String(150))

    # Fabricante específico desta apresentação.
    # Um mesmo Medicamento (ex.: "Prednisona") pode ter apresentações
    # da LigVet, Animalia, genérico, etc.
    fabricante           = db.Column(db.String(150))

    # Origem no VetSmart (produto comercial de onde veio a apresentação).
    vetsmart_produto_id  = db.Column(db.Integer, index=True)

    def __str__(self):
        return f"{self.medicamento.nome} – {self.forma} ({self.concentracao})"


class DoseMedicamento(db.Model):
    __tablename__ = 'dose_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    medicamento_id = db.Column(db.Integer, db.ForeignKey('medicamento.id', ondelete='CASCADE'), nullable=False)

    especie = db.Column(db.String(80))          # Ex: "Cães", "Gatos", "Cães e Gatos"
    faixa_peso = db.Column(db.String(80))       # Ex: "Até 4 kg", "Entre 10 e 25 kg"
    via = db.Column(db.String(80))              # Ex: "Oral", "Tópica"
    dose = db.Column(db.String(200))            # Ex: "20 - 30 mg/kg", "0,4 mL/animal"
    frequencia = db.Column(db.String(120))      # Ex: "A cada 12 horas"
    duracao = db.Column(db.String(120))         # Ex: "7 dias"
    observacao = db.Column(db.Text)             # Notas/modo de usar

    # Campos numéricos para cálculo automático
    especie_code       = db.Column(db.String(10))              # 'CAES' | 'GATOS' | 'AMBOS' | 'OUTRO'
    peso_min_kg        = db.Column(db.Numeric(8, 2))           # null = sem mínimo
    peso_max_kg        = db.Column(db.Numeric(8, 2))           # null = sem máximo
    dose_min           = db.Column(db.Numeric(12, 3))
    dose_max           = db.Column(db.Numeric(12, 3))
    dose_unidade       = db.Column(db.String(30))              # 'MG_KG'|'ML_KG'|'UI_KG'|'MG_ANIMAL'|...
    intervalo_horas    = db.Column(db.Integer)                 # valor único (retrocompat)
    intervalo_min_horas = db.Column(db.Integer)               # null se não há faixa
    intervalo_max_horas = db.Column(db.Integer)               # null se não há faixa
    duracao_min_dias   = db.Column(db.Integer)
    duracao_max_dias   = db.Column(db.Integer)
    dose_raw_text      = db.Column(db.Text)                    # trecho original do VetSmart
    fonte              = db.Column(db.String(15), default='HUMANO')  # 'SCRAPER'|'LLM'|'HUMANO'
    confianca          = db.Column(db.String(10), default='MEDIA')   # 'ALTA'|'MEDIA'|'BAIXA'

    # Indicação clínica desta dose (Alergia, Imunossupressão, Dermatite atópica, ...).
    # NULL quando o parser não consegue inferir com confiança — nesse caso o
    # calculador de dose exibe todas as doses disponíveis e deixa o vet escolher.
    indicacao          = db.Column(db.String(120), index=True)

    def __str__(self):
        partes = [p for p in [self.especie, self.faixa_peso, self.dose] if p]
        return " · ".join(partes) or f"Dose #{self.id}"


class PrescricaoAliasMedicamento(db.Model):
    """Mapeia texto exato de prescrição histórica ao medicamento canônico.

    Permite que nomes como 'Dipirona – 500 mg/mL, gotas' (formato VetSmart com em-dash)
    sejam resolvidos ao ID correto sem match exato no nome do Medicamento.
    confianca: 'exato' | 'normalizado' | 'prefixo' | 'variante' | 'substring' | 'manual' | 'sem_match'
    """
    __tablename__ = 'prescricao_alias_medicamento'
    id = db.Column(db.Integer, primary_key=True)
    nome_prescrito = db.Column(db.Text, nullable=False, unique=True)
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamento.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    confianca = db.Column(db.String(20), nullable=False, default='auto')
    criado_em = db.Column(db.DateTime(timezone=True), server_default=db.func.now())


class CuradoriaMedicamentoReview(db.Model):
    """Fila de curadoria clínica gerada a partir do histórico de prescrições.

    A revisão guarda propostas e diagnósticos, mas não altera o bulário até uma
    etapa posterior de aprovação explícita.
    """
    __tablename__ = 'curadoria_medicamento_review'

    id = db.Column(db.Integer, primary_key=True)
    nome_normalizado = db.Column(db.String(180), nullable=False, unique=True, index=True)
    nome_prescrito_principal = db.Column(db.Text, nullable=False)
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamento.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    medicamento = db.relationship('Medicamento', backref=db.backref('curadorias_review', lazy='dynamic'))

    status = db.Column(db.String(20), nullable=False, default='pendente', index=True)
    prioridade = db.Column(db.Integer, nullable=False, default=0, index=True)
    total_prescricoes = db.Column(db.Integer, nullable=False, default=0)
    ultima_prescricao_em = db.Column(db.DateTime(timezone=True))
    confianca_alias = db.Column(db.String(20), nullable=False, default='sem_match')

    resumo_historico = db.Column(db.JSON)
    diagnostico = db.Column(db.JSON)
    proposta = db.Column(db.JSON)
    fontes = db.Column(db.JSON)

    criado_em = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    atualizado_em = db.Column(
        db.DateTime(timezone=True),
        default=now_in_brazil,
        onupdate=now_in_brazil,
        nullable=False,
    )
    aprovado_em = db.Column(db.DateTime(timezone=True))
    aprovado_por_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    aprovado_por = db.relationship('User', foreign_keys=[aprovado_por_id])

    def __repr__(self):
        return f'<CuradoriaMedicamentoReview {self.nome_prescrito_principal!r} status={self.status}>'


class MedicamentoFavorito(db.Model):
    """Medicamentos marcados como favoritos por um veterinário."""
    __tablename__ = 'medicamento_favorito'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    medicamento_id = db.Column(
        db.Integer,
        db.ForeignKey('medicamento.id', ondelete='CASCADE'),
        nullable=False,
    )
    criado_em = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint('user_id', 'medicamento_id', name='uq_fav_user_med'),
    )

