"""Seed do medicamento Frontline Plus, suas 5 apresentações e doses estruturadas.

Pode ser executado diretamente em qualquer ambiente (dev/prod):
    python scripts/seed_frontline_plus.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_factory import create_app
from extensions import db
from models.base import User
from models.bulario import (
    Medicamento,
    ApresentacaoMedicamento,
    DoseMedicamento,
    PrescricaoAliasMedicamento,
)


APRESENTACOES_FRONTLINE = [
    {
        "forma": "Pipeta",
        "concentracao": "Gatos até 10 Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus gatos até 10 Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 0.50,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães até 10 Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães até 10 Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 0.67,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães de 10 Kg a 20Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães de 10 Kg a 20Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 1.34,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães de 20 Kg a 40Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães de 20 Kg a 40Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 2.68,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
    {
        "forma": "Pipeta",
        "concentracao": "Cães de 40 Kg a 60Kg, pipeta (1 un)",
        "nome_variante": "Frontline® Plus cães de 40 Kg a 60Kg, pipeta (1 un)",
        "nome_comercial": "Frontline Plus",
        "volume_valor": 4.02,
        "volume_unidade": "mL",
        "fabricante": "Boehringer Ingelheim",
        "vetsmart_produto_id": 63,
    },
]

DOSES_FRONTLINE = [
    {
        "especie": "Gatos",
        "especie_code": "GATOS",
        "faixa_peso": "Até 10 kg",
        "peso_min_kg": 0.00,
        "peso_max_kg": 10.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (0,5 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Gatos até 10 kg: 1 pipeta (0,5 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca do felino, afastando os pelos para evitar lambedura.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "Até 10 kg",
        "peso_min_kg": 0.00,
        "peso_max_kg": 10.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (0,67 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães até 10 kg: 1 pipeta (0,67 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "10 a 20 kg",
        "peso_min_kg": 10.01,
        "peso_max_kg": 20.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (1,34 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães de 10 a 20 kg: 1 pipeta (1,34 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "20 a 40 kg",
        "peso_min_kg": 20.01,
        "peso_max_kg": 40.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (2,68 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães de 20 a 40 kg: 1 pipeta (2,68 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
    {
        "especie": "Cães",
        "especie_code": "CAES",
        "faixa_peso": "40 a 60 kg",
        "peso_min_kg": 40.01,
        "peso_max_kg": 60.00,
        "via": "Tópica",
        "dose": "1 pipeta / animal (4,02 mL)",
        "frequencia": "A cada 30 dias",
        "duracao": "Dose única (repetir mensalmente se necessário)",
        "dose_min": 1,
        "dose_max": 1,
        "dose_unidade": "PIPETA_ANIMAL",
        "intervalo_horas": 720,
        "intervalo_min_horas": 720,
        "intervalo_max_horas": 720,
        "dose_raw_text": "Frontline Plus Cães de 40 a 60 kg: 1 pipeta (4,02 mL) tópica a cada 30 dias.",
        "observacao": "Aplicar todo o conteúdo da pipeta diretamente na pele da nuca ou entre as escápulas do cão, afastando os pelos.",
        "indicacao": "Controle de ectoparasitas (pulgas e carrapatos)",
        "fonte": "HUMANO",
        "confianca": "ALTA",
    },
]

ALIASES_FRONTLINE = [
    "Frontline",
    "Frontline Plus",
    "Frontline® Plus",
    "Fipronil",
    "Fipronil + (S)-Metopreno",
    "Frontline Plus Cães",
    "Frontline Plus Gatos",
    "Frontline Plus – Gatos até 10 Kg, pipeta (1 un)",
    "Frontline Plus – Cães até 10 Kg, pipeta (1 un)",
    "Frontline Plus – Cães de 10 Kg a 20Kg, pipeta (1 un)",
    "Frontline Plus – Cães de 20 Kg a 40Kg, pipeta (1 un)",
    "Frontline Plus – Cães de 40 Kg a 60Kg, pipeta (1 un)",
]


def seed_frontline_plus():
    app = create_app()
    with app.app_context():
        user = User.query.order_by(User.id).first()
        if not user:
            user = User(
                name="Administrador do Sistema",
                email="admin_seed@petorlandia.com.br",
                password_hash="pbkdf2:sha256:seed_placeholder_hash",
                role="admin",
            )
            db.session.add(user)
            db.session.flush()

        # 1. Medicamento
        med = (
            Medicamento.query.filter(
                (Medicamento.nome.ilike("Frontline Plus"))
                | (Medicamento.nome.ilike("Frontline"))
                | (Medicamento.vetsmart_produto_id == 63)
            )
            .first()
        )

        if not med:
            med = Medicamento(
                nome="Frontline Plus",
                classificacao="Ectoparasiticida",
                principio_ativo="Fipronil + (S)-Metopreno",
                via_administracao="Tópica",
                dosagem_recomendada="1 pipeta / animal conforme a espécie e faixa de peso",
                frequencia="A cada 30 dias",
                duracao_tratamento="Dose única (repetir mensalmente para controle contínuo)",
                observacoes=(
                    "Afaste os pelos do animal na região da nuca ou entre as escápulas até que a pele fique visível. "
                    "Aplique todo o conteúdo da pipeta diretamente sobre a pele seca. Evitar banhos ou natação 48 horas "
                    "antes e após a aplicação. Não utilizar em filhotes de cães com menos de 8 semanas de idade ou em "
                    "gatos com menos de 8 semanas e/ou pesando menos de 1 kg."
                ),
                species_scope="CG",
                vetsmart_produto_id=63,
                created_by=user.id,
            )
            db.session.add(med)
            db.session.flush()
            print(f"[OK] Medicamento criado: {med.nome} (ID: {med.id})")
        else:
            med.nome = "Frontline Plus"
            med.classificacao = "Ectoparasiticida"
            med.principio_ativo = "Fipronil + (S)-Metopreno"
            med.via_administracao = "Tópica"
            med.species_scope = "CG"
            med.vetsmart_produto_id = 63
            print(f"[OK] Medicamento existente atualizado: {med.nome} (ID: {med.id})")

        # 2. Apresentações
        for item in APRESENTACOES_FRONTLINE:
            apres = ApresentacaoMedicamento.query.filter_by(
                medicamento_id=med.id,
                concentracao=item["concentracao"],
            ).first()

            if not apres:
                apres = ApresentacaoMedicamento.query.filter_by(
                    medicamento_id=med.id,
                    nome_variante=item["nome_variante"],
                ).first()

            if not apres:
                apres = ApresentacaoMedicamento(medicamento_id=med.id, **item)
                db.session.add(apres)
                print(f"  + Apresentação inserida: {item['nome_variante']}")
            else:
                for k, v in item.items():
                    setattr(apres, k, v)
                print(f"  ~ Apresentação atualizada: {item['nome_variante']}")

        # 3. Doses
        for item in DOSES_FRONTLINE:
            dose = DoseMedicamento.query.filter_by(
                medicamento_id=med.id,
                especie_code=item["especie_code"],
                faixa_peso=item["faixa_peso"],
                dose_unidade=item["dose_unidade"],
            ).first()

            if not dose:
                dose = DoseMedicamento(medicamento_id=med.id, **item)
                db.session.add(dose)
                print(f"  + Dose inserida: {item['especie']} ({item['faixa_peso']}) - {item['dose']}")
            else:
                for k, v in item.items():
                    setattr(dose, k, v)
                print(f"  ~ Dose atualizada: {item['especie']} ({item['faixa_peso']}) - {item['dose']}")

        # 4. Aliases
        for alias_nome in ALIASES_FRONTLINE:
            alias = PrescricaoAliasMedicamento.query.filter_by(nome_prescrito=alias_nome).first()
            if not alias:
                alias = PrescricaoAliasMedicamento(
                    nome_prescrito=alias_nome,
                    medicamento_id=med.id,
                    confianca="manual",
                )
                db.session.add(alias)
            else:
                alias.medicamento_id = med.id
                alias.confianca = "manual"

        db.session.commit()
        print("\n[SUCESSO] Frontline Plus e todas as 5 apresentações e doses cadastradas com sucesso!")


if __name__ == "__main__":
    seed_frontline_plus()
