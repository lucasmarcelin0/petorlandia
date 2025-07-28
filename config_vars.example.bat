@echo off
rem Example script to configure variables on Heroku

rem ===== AWS =====
heroku config:set AWS_ACCESS_KEY_ID="YOUR_AWS_ACCESS_KEY_ID"
heroku config:set AWS_SECRET_ACCESS_KEY="YOUR_AWS_SECRET_KEY"
heroku config:set S3_BUCKET_NAME="your-bucket"

rem ===== Mercado Pago =====
heroku config:set MERCADOPAGO_ACCESS_TOKEN="your-access-token"
heroku config:set MERCADOPAGO_PUBLIC_KEY="your-public-key"
heroku config:set MERCADOPAGO_WEBHOOK_SECRET="your-webhook-secret"

rem ===== Flask-Mail =====
heroku config:set MAIL_SERVER="smtp.gmail.com"
heroku config:set MAIL_PORT="587"
heroku config:set MAIL_USE_TLS="True"
heroku config:set MAIL_USE_SSL="False"
heroku config:set MAIL_USERNAME="your-email@example.com"
heroku config:set MAIL_PASSWORD="app-password"
heroku config:set MAIL_DEFAULT_SENDER_NAME="PetOrlândia"
heroku config:set MAIL_DEFAULT_SENDER_EMAIL="your-email@example.com"

rem ===== Flask App Settings =====
heroku config:set SECRET_KEY="change-me"
heroku config:set SQLALCHEMY_DATABASE_URI="postgresql://user:password@host:5432/dbname"

rem ===== Default Pickup Address =====
heroku config:set DEFAULT_PICKUP_ADDRESS="Rua nove 990 - orlandia"

echo ================================
echo Variables sent!
pause
