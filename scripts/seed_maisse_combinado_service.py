#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Seed e configuração do serviço da Dra. Maisse Cividanes e modelo do Combinado para a Clínica PetOrlandia."""

import os
import sys
from decimal import Decimal

# Garantir path do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from models import (
    ExameModelo,
    ServicoClinica,
    ProfessionalService,
    Veterinario,
)
from sqlalchemy import func


def seed_maisse_combinado():
    with app.app_context():
        print("=== Iniciando Seed do Serviço Combinado da Dra. Maisse ===")

        # 1. Atualizar ExameModelo (isolar para clinica_id = 1)
        exame_m = ExameModelo.query.filter(
            func.lower(ExameModelo.nome).like('%combinado%hemograma%')
        ).first()

        if exame_m:
            print(f"Encontrado ExameModelo id={exame_m.id} ('{exame_m.nome}')")
            if exame_m.clinica_id != 1:
                exame_m.clinica_id = 1
                print(" -> Atualizado clinica_id = 1 (Clínica PetOrlandia)")
            else:
                print(" -> clinica_id já estava definido como 1")
        else:
            print("Criando novo ExameModelo 'Combinado - Hemograma, ALT, FA, ureia, creatinina' para clinica_id=1")
            exame_m = ExameModelo(
                nome='Combinado - Hemograma, ALT, FA, ureia, creatinina',
                justificativa='Exame solicitado para avaliação geral do estado de saúde e suporte ao diagnóstico clínico.',
                created_by=1,
                clinica_id=1,
            )
            db.session.add(exame_m)

        # 2. Cadastrar / Atualizar ServicoClinica para a PetOrlandia (clinica_id = 1)
        title = 'Combinado - Hemograma, ALT, FA, ureia, creatinina'
        servico = ServicoClinica.query.filter_by(
            clinica_id=1,
            descricao=title,
        ).first()

        if not servico:
            print(f"Criando ServicoClinica '{title}' para clinica_id=1 com valor R$ 110.00")
            servico = ServicoClinica(
                clinica_id=1,
                descricao=title,
                valor=Decimal('110.00'),
                procedure_code='LAB-MAISSE',
            )
            db.session.add(servico)
        else:
            print(f"ServicoClinica id={servico.id} já existe com valor R$ {servico.valor}")
            if servico.valor != Decimal('110.00'):
                servico.valor = Decimal('110.00')
                print(" -> Valor atualizado para R$ 110.00")

        # 3. Localizar Dra. Maisse e configurar ProfessionalService
        from models import User
        vet = (
            Veterinario.query
            .join(User, Veterinario.user_id == User.id)
            .filter(
                (Veterinario.id == 430) |
                (User.email == 'maissecividanes@hotmail.com') |
                (User.name.ilike('%Maisse%Cividanes%'))
            )
            .first()
        )

        if vet:
            print(f"Veterinária encontrada: id={vet.id}, nome='{getattr(vet.user, 'name', '')}', email='{getattr(vet.user, 'email', '')}'")
            ps = ProfessionalService.query.filter(
                ProfessionalService.veterinario_id == vet.id,
                func.lower(ProfessionalService.title).like('%combinado%hemograma%'),
            ).first()

            if not ps:
                print(f"Criando ProfessionalService '{title}' para Dra. Maisse (id={vet.id})")
                ps = ProfessionalService(
                    veterinario_id=vet.id,
                    service_type='exame',
                    title=title,
                    description='Exame laboratorial combinado: Hemograma completo, ALT (TGP), Fosfatase Alcalina (FA), Ureia e Creatinina.',
                    audience='both',
                    mode='clinica',
                    duration_minutes=30,
                    clinic_business_price=Decimal('100.00'),
                    tutor_price=Decimal('110.00'),
                    active=True,
                )
                db.session.add(ps)
            else:
                print(f"ProfessionalService id={ps.id} já existe. Atualizando dados...")
                ps.title = title
                ps.service_type = 'exame'
                ps.clinic_business_price = Decimal('100.00')
                ps.tutor_price = Decimal('110.00')
                ps.audience = 'both'
                ps.active = True
        else:
            print("AVISO: Dra. Maisse não foi encontrada no banco local (pode ser ambiente de dev).")

        db.session.commit()
        print("=== Seed finalizado com sucesso! ===")


if __name__ == '__main__':
    seed_maisse_combinado()
