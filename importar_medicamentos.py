import os
import sys
import pandas as pd

# Garante que o Python encontre os módulos locais
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import Medicamento
from extensions import db

if __name__ == "__main__":
    with app.app_context():
        df = pd.read_csv("medicamentos_pet_orlandia.csv")

        for _, row in df.iterrows():
            medicamento = Medicamento(
                classificacao=row["classificacao"],
                nome=row["nome"],
                principio_ativo=row["principio_ativo"],
                via_administracao=row["via_administracao"],
                dosagem_recomendada=row["dosagem_recomendada"],
                duracao_tratamento=row["duracao_tratamento"],
                observacoes=row["observacoes"],
                bula=row["link_bula"]
            )
            db.session.add(medicamento)

        db.session.commit()
        print("✅ Medicamentos importados com sucesso!")
