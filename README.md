# PetOrlândia

PetOrlândia é uma aplicação web em Flask voltada para o gerenciamento de animais de estimação, incluindo funcionalidades de adoção, cadastro de animais e um pequeno e-commerce para produtos pet.

## Configuração do ambiente

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Copie o arquivo `.env` de exemplo ou crie um novo `.env` na raiz do projeto e defina as variáveis necessárias (veja abaixo).

## Variáveis de ambiente principais

- `SECRET_KEY` – chave secreta do Flask.
- `SQLALCHEMY_DATABASE_URI` – URL de conexão com o banco PostgreSQL.
- `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD` – configurações de e-mail.
- `FRONTEND_URL` – URL base usada em links de e-mail (padrão `http://127.0.0.1:5000`).
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `S3_BUCKET_NAME` – credenciais do bucket S3 para upload de arquivos.
- `PORT` – porta usada no modo standalone (opcional, padrão 5000).

## Migrações do banco de dados

O projeto utiliza Flask-Migrate. Para criar ou atualizar a estrutura do banco:

```bash
flask db upgrade      # aplica as migrações existentes
flask db migrate -m "mensagem"  # cria nova migração (opcional)
```

## Executando a aplicação

Com as dependências instaladas e variáveis configuradas:

```bash
flask run                 # ou
python app.py             # ou
gunicorn app:app          # usado em produção/Procfile
```

A aplicação ficará acessível em `http://localhost:5000` (ou na porta definida em `PORT`).

## Serviço adicional: Amazon S3

Uploads de imagens e documentos são armazenados em um bucket S3. Certifique-se de:

1. Criar um bucket na AWS.
2. Definir `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `S3_BUCKET_NAME` no arquivo `.env`.
3. Conceder permissões adequadas para upload no bucket.

