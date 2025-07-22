import os
import mercadopago
from pprint import pprint

# 1) Access-token de produção ou sandbox (via variável de ambiente é o ideal)
ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "APP_USR-6670170005169574-071911-23502e25ef4bc98e3e2f9706cd082550-99814908")

    

sdk = mercadopago.SDK(ACCESS_TOKEN)

# 2) Dados da preferência
preference_data = {
    "items": [
        {
            "title": "Ração Premium 10 kg",
            "quantity": 1,
            "unit_price": 149.90
        }
    ],
    "external_reference": "1234",                 # ID interno (ex.: payment.id)
    "notification_url": "https://www.petorlandia.com.br/notificacoes",
    "back_urls": {
        "success": "https://www.petorlandia.com.br/pagamento/sucesso",
        "pending": "https://www.petorlandia.com.br/pagamento/pendente",
        "failure": "https://www.petorlandia.com.br/pagamento/erro"
    },
    "auto_return": "approved",                    # volta automático se aprovar
    "payment_methods": {
        "installments": 1,                        # 1 parcela (à vista)
        # "default_payment_method_id": "pix"      # força PIX se quiser
    }
}

# 3) Criação
response = sdk.preference().create(preference_data)

# 4) Conferindo resultado
if response["status"] == 201:
    pref = response["response"]
    print("✅ Preference criada!")
    print("pref_id:", pref["id"])
    print("Checkout PROD:", pref["init_point"])
    print("Checkout SANDBOX:", pref["sandbox_init_point"])
else:
    print("❌ Erro HTTP", response["status"])
    pprint(response)