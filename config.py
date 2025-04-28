import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = 'supersegredo123'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'petorlandia.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = 'gpt.assistente.orlandia@gmail.com'
    MAIL_PASSWORD = 'tpezhrlnqawjslxg'  # <--- pasted App Password here
    MAIL_DEFAULT_SENDER = ('PetOrlândia', 'gpt.assistente.orlandia@gmail.com')
