from app_factory import create_app
from extensions import db
from models.base import SiteFlag

app = create_app()
with app.app_context():
    SiteFlag.set('loja_em_breve', True, 'Loja PetOrlândia — Em breve')
    SiteFlag.set('plano_saude_em_breve', True, 'Plano de Saúde — Em breve')
    print("Seed de flags concluído com sucesso!")
