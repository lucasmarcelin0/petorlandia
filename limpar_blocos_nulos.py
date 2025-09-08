from app import app, db
from models import Animal, BlocoExames, ExameSolicitado, Consulta

with app.app_context():
    blocos = BlocoExames.query.filter_by(animal_id=None).all()

    if not blocos:
        print("✅ Nenhum bloco de exame com animal_id nulo encontrado.")
    else:
        print(f"🔍 Corrigindo {len(blocos)} blocos de exame com animal_id nulo...")

        blocos_corrigidos = 0
        exames_corrigidos = 0

        for bloco in blocos:
            if bloco.consulta and bloco.consulta.animal_id:
                bloco.animal_id = bloco.consulta.animal_id
                blocos_corrigidos += 1

                for exame in bloco.exames:
                    exame.animal_id = bloco.animal_id
                    exames_corrigidos += 1

        db.session.commit()

        print(f"✅ {blocos_corrigidos} blocos de exame preenchidos com sucesso.")
        print(f"✅ {exames_corrigidos} exames preenchidos com sucesso.")

        restantes = BlocoExames.query.filter_by(animal_id=None).count()
        print(f"🔍 Blocos ainda com animal_id nulo: {restantes}")
