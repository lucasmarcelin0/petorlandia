@echo off
echo ================================
echo Fazendo backup das variáveis do Heroku
echo ================================

REM Nome do app Heroku
SET APP_NAME=petorlandia

REM Arquivo de destino
SET BACKUP_FILE=heroku_backup.env

echo Salvando variáveis em %BACKUP_FILE%...

REM Exporta todas as config vars do Heroku para um arquivo .env
heroku config -a %APP_NAME% --shell > %BACKUP_FILE%

echo ================================
echo Backup concluído com sucesso!
echo Arquivo salvo como %BACKUP_FILE%
pause
