@echo off
echo =========================================
echo   🚀 Setup Inteligente PetOrlândia Local
echo =========================================

REM ==== Login no Heroku ====
echo 🔑 Efetuando login no Heroku...
heroku login
if %errorlevel% neq 0 (
    echo ❌ Falha no login do Heroku. Execute novamente.
    pause
    exit /b
)

REM ==== Verifica se pasta já existe ====
IF EXIST petorlandia (
    echo 📂 Pasta encontrada. Atualizando projeto...
    cd petorlandia
    git pull origin main
) ELSE (
    echo 📂 Pasta não encontrada. Clonando projeto...
    heroku git:clone -a petorlandia
    cd petorlandia
)

REM ==== Cria ambiente virtual se não existir ====
IF NOT EXIST venv (
    echo 🐍 Criando ambiente virtual...
    python -m venv venv
)

REM ==== Ativando ambiente virtual ====
echo 🔄 Ativando ambiente virtual...
call venv\Scripts\activate

REM ==== Instalando dependências ====
echo 📦 Instalando dependências...
pip install -r requirements.txt

REM ==== Baixando variáveis do Heroku ====
echo 🔑 Baixando variáveis do Heroku para .env...
heroku config -a petorlandia --shell > .env

REM ==== Abrindo navegador ====
echo 🌐 Abrindo navegador em http://127.0.0.1:5000 ...
start "" http://127.0.0.1:5000

REM ==== Rodando servidor Flask ====
echo ▶️ Iniciando servidor Flask...
flask run

pause
