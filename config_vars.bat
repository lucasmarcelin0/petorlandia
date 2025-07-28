@echo off
echo ================================
echo Configurando variáveis no Heroku
echo ================================

REM ===== AWS =====
heroku config:set AWS_ACCESS_KEY_ID="AKIA5R6GP4YL7EQXIBDZ"
heroku config:set AWS_SECRET_ACCESS_KEY="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"
heroku config:set S3_BUCKET_NAME="petorlandia"

REM ===== Mercado Pago =====
heroku config:set MERCADOPAGO_ACCESS_TOKEN="APP_USR-6670170005169574-071911-23502e25ef4bc98e3e2f9706cd082550-99814908"
heroku config:set MERCADOPAGO_PUBLIC_KEY="APP_USR-2b9a9bff-692b-4de8-9b90-ce9aa758ca14"
heroku config:set MERCADOPAGO_WEBHOOK_SECRET="add6cb517c10e98c1decbe37a4290a41b45a9b3b1d04a5d368babd18a2969d44"

REM ===== Flask-Mail =====
heroku config:set MAIL_SERVER="smtp.gmail.com"
heroku config:set MAIL_PORT="587"
heroku config:set MAIL_USE_TLS="True"
heroku config:set MAIL_USE_SSL="False"
heroku config:set MAIL_USERNAME="gpt.assistente.orlandia@gmail.com"
heroku config:set MAIL_PASSWORD="toso zrgb uuwx nzkp"
heroku config:set MAIL_DEFAULT_SENDER_NAME="PetOrlândia"
heroku config:set MAIL_DEFAULT_SENDER_EMAIL="gpt.assistente.orlandia@gmail.com"

REM ===== Flask App Settings =====
heroku config:set SECRET_KEY="dev-key"
heroku config:set SQLALCHEMY_DATABASE_URI="postgresql://u82pgjdcmkbq7v:***@c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli"

REM ===== Default Pickup Address =====
heroku config:set DEFAULT_PICKUP_ADDRESS="Rua nove 990 - orlandia"

echo ================================
echo Todas as variáveis foram enviadas!
pause
