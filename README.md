# PetOrlândia

PetOrlândia é uma aplicação web construída com Flask voltada para o gerenciamento de animais e para uma pequena loja virtual. O projeto oferece funcionalidades de cadastro de usuários e animais, controle de consultas, trocas de mensagens e administração via Flask‑Admin, além de upload de imagens para o Amazon S3.

## Configuração do ambiente

1. **Python**: utilize a versão especificada em `runtime.txt` (atualmente `python-3.12.3`).
2. Crie um ambiente virtual e instale as dependências:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Configure as variáveis de ambiente em um arquivo `.env` na raiz do projeto. Exemplo:

```env
AWS_ACCESS_KEY_ID=SEU_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=SEU_SECRET_KEY
S3_BUCKET_NAME=nome-do-bucket
FRONTEND_URL=http://localhost:5000
PORT=5000
```

É recomendado definir também `FLASK_APP=app` para executar os comandos do Flask.

## Execução do aplicativo

Para iniciar em modo de desenvolvimento:

```bash
flask --app app run --debug
```

ou diretamente com Python:

```bash
python app.py
```

Em produção a aplicação pode ser servida através do `gunicorn` conforme o `Procfile`:

```bash
gunicorn app:app
```

## Migrações de banco de dados

O projeto utiliza **Flask‑Migrate**. Para inicializar e aplicar migrações:

```bash
# Executar apenas uma vez ao criar o repositório de migrações
flask db init

# Gerar uma nova migração
flask db migrate -m "Mensagem da migração"

# Aplicar alterações ao banco
flask db upgrade
```

As configurações de conexão estão definidas em `config.py` e podem ser ajustadas conforme necessário.

## Serviços adicionais

### Amazon S3
Uploads de imagens (por exemplo, fotos de animais e perfis) são enviados ao Amazon S3. Certifique‑se de fornecer suas credenciais e o nome do bucket através das variáveis de ambiente mencionadas anteriormente. O utilitário de upload está implementado em [`s3_utils.py`](s3_utils.py).

---
Este README resume os principais passos para iniciar e manter a aplicação. Consulte o código‑fonte para detalhes adicionais sobre cada funcionalidade.
