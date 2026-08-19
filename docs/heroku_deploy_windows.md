# Deploy seguro no Heroku (Windows)

Use o script de preflight para publicar o commit atual:

```powershell
.\scripts\deploy_heroku.ps1
```

Para executar testes antes de publicar:

```powershell
.\scripts\deploy_heroku.ps1 -TestPath tests\test_routes.py -PytestArgs '-k','vacina_pmo_dashboard'
```

Para validar branch, remoto e arvore de trabalho sem publicar:

```powershell
.\scripts\deploy_heroku.ps1 -PreflightOnly
```

O script:

- busca `heroku/main` antes de decidir se o push e seguro;
- impede deploy com alteracoes rastreadas sem commit;
- recusa historicos divergentes sem sobrescrever a producao;
- envia `HEAD:main`, independentemente do nome da branch local;
- confirma que o Heroku recebeu exatamente o commit esperado.

Nao use `git push heroku main` quando o `main` local estiver desatualizado. Nao
use `--force` para contornar rejeicoes: isso pode apagar correcoes presentes em
producao.

## Ambiente Python quebrado

Um ambiente virtual guarda o caminho exato do Python usado na sua criacao. A
Microsoft Store pode remover esse caminho ao atualizar o Python, deixando o
`.venv` existente incapaz de iniciar.

Reinstale o Python 3.12 e recrie o ambiente:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

O deploy do Heroku cria um ambiente Python novo no servidor e, por isso, nao
depende do `.venv` local. O ambiente local funcional continua necessario para
executar os testes antes de publicar.
