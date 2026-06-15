from app import app; from extensions import db; from models import User; import secrets
with app.app_context():
    email = 'cvorlandia@gmail.com'
    u = User.query.filter_by(email=email).first()
    if u:
        u.name = 'Controle de Vetores'; u.role = 'vacinador'; db.session.commit()
        print('Usuario atualizado:', email)
    else:
        pwd = secrets.token_urlsafe(10)
        u = User(name='Controle de Vetores', email=email, role='vacinador', password_hash='x')
        u.set_password(pwd); db.session.add(u); db.session.commit()
        print('Usuario criado:', email); print('Senha inicial:', pwd)
